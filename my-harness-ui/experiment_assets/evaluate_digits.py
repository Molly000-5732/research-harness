"""Trusted evaluator: model-generated code only constructs the three estimators."""
import argparse
import ast
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import numpy as np
import sklearn
from sklearn.datasets import load_digits
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC


def load_factory(source):
    tree = ast.parse(source, filename="models.py")
    imports = {"sklearn.linear_model": {"LogisticRegression"}, "sklearn.svm": {"SVC"}}
    allowed = (ast.Module, ast.ImportFrom, ast.alias, ast.FunctionDef, ast.arguments, ast.arg,
               ast.Return, ast.Dict, ast.Call, ast.Name, ast.Load, ast.keyword, ast.Constant)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError("models.py 只允许分类器导入及返回模型字典的工厂函数")
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module not in imports or any(a.name not in imports[node.module] or a.asname for a in node.names):
                raise ValueError("不支持的导入")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in {"LogisticRegression", "SVC"}):
            raise ValueError("只能构造指定的分类器")
        if isinstance(node, ast.Name) and node.id not in {"LogisticRegression", "SVC", "seed"}:
            raise ValueError("不支持的名称")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ValueError("不支持的常量")
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(funcs) != 1 or any(not isinstance(node, (ast.ImportFrom, ast.FunctionDef)) for node in tree.body):
        raise ValueError("必须只定义 build_models(seed)")
    func = funcs[0]
    args = func.args
    if (func.name != "build_models" or func.decorator_list or func.returns or len(args.args) != 1
            or args.args[0].arg != "seed" or args.args[0].annotation or args.posonlyargs or args.kwonlyargs
            or args.defaults or args.kw_defaults or args.vararg or args.kwarg
            or len(func.body) != 1 or not isinstance(func.body[0], ast.Return)
            or not isinstance(func.body[0].value, ast.Dict)):
        raise ValueError("工厂必须只有 return 模型字典")
    for value in func.body[0].value.values:
        if not isinstance(value, ast.Call) or value.args:
            raise ValueError("模型必须用关键字参数直接构造")
        for keyword in value.keywords:
            if keyword.arg is None or not (isinstance(keyword.value, ast.Constant) or
                                          isinstance(keyword.value, ast.Name) and keyword.value.id == "seed"):
                raise ValueError("模型参数只能是常量或 seed")
    # Imports were validated above. Do not execute arbitrary import machinery.
    module = ast.Module(body=[func], type_ignores=[])
    namespace = {"__builtins__": {}, "LogisticRegression": LogisticRegression, "SVC": SVC}
    exec(compile(module, "models.py", "exec"), namespace)
    return namespace["build_models"]


def validate_models(models, seed):
    if not isinstance(models, dict) or set(models) != {"baseline", "ablation", "improved"}:
        raise ValueError("工厂必须返回 baseline、ablation、improved")
    if type(models["baseline"]) is not LogisticRegression or any(type(models[name]) is not SVC for name in ("ablation", "improved")):
        raise ValueError("模型类型与协议不符")
    b = models["baseline"].get_params()
    if b != LogisticRegression(C=1.0, max_iter=1000, random_state=seed).get_params():
        raise ValueError("基线参数必须严格遵守协议")
    expected = SVC(C=10.0, kernel="rbf", gamma="scale").get_params()
    for name in ("ablation", "improved"):
        params = models[name].get_params()
        # random_state does not affect SVC with probability=False, but accept seed for reproducibility.
        if params.pop("random_state") not in (None, seed) or params != {k: v for k, v in expected.items() if k != "random_state"}:
            raise ValueError("RBF 模型参数必须严格遵守协议")
    if len({id(model) for model in models.values()}) != 3:
        raise ValueError("必须返回独立模型")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--protocol", required=True)
    args = parser.parse_args()
    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    if protocol["id"] != "digits-noise-v1":
        raise ValueError("不支持的实验类型")
    factory = load_factory(Path(args.source).read_text(encoding="utf-8"))
    dataset = load_digits()
    x, y = dataset.data.astype(np.float64) / 16.0, dataset.target
    rows, splits, examples = [], [], []
    for seed in protocol["seeds"]:
        pool_idx, test_idx = train_test_split(np.arange(len(y)), test_size=protocol["testFraction"], stratify=y, random_state=seed)
        train_idx, _ = train_test_split(pool_idx, train_size=protocol["trainSamples"], stratify=y[pool_idx], random_state=seed)
        assert not np.intersect1d(train_idx, test_idx).size
        rng = np.random.default_rng(seed)
        x_train, y_train, x_test, y_test = x[train_idx], y[train_idx], x[test_idx], y[test_idx]
        # Identical noisy test inputs for all three methods, never used in fitting.
        noisy_test = np.clip(x_test + rng.normal(0, protocol["testNoiseSigma"], x_test.shape), 0, 1)
        augmented = [x_train] + [np.clip(x_train + rng.normal(0, protocol["augmentationSigma"], x_train.shape), 0, 1)
                                 for _ in range(protocol["augmentationCopies"])]
        augmented_x = np.concatenate(augmented)
        augmented_y = np.tile(y_train, protocol["augmentationCopies"] + 1)
        models = factory(seed)
        validate_models(models, seed)
        splits.append({"seed": seed, "trainCount": len(train_idx), "testCount": len(test_idx),
                       "overlap": 0, "trainSha256": hashlib.sha256(train_idx.tobytes()).hexdigest(),
                       "testSha256": hashlib.sha256(test_idx.tobytes()).hexdigest()})
        for method in protocol["models"]:
            model = models[method]
            started = time.perf_counter()
            model.fit(augmented_x if method == "improved" else x_train, augmented_y if method == "improved" else y_train)
            duration = time.perf_counter() - started
            clean_pred, noisy_pred = model.predict(x_test), model.predict(noisy_test)
            rows.append({"seed": seed, "method": method, "trainCount": len(augmented_y) if method == "improved" else len(y_train),
                         "cleanAccuracy": float(accuracy_score(y_test, clean_pred)), "noisyAccuracy": float(accuracy_score(y_test, noisy_pred)),
                         "cleanMacroF1": float(f1_score(y_test, clean_pred, average="macro")),
                         "noisyMacroF1": float(f1_score(y_test, noisy_pred, average="macro")), "fitSeconds": duration,
                         "noisyConfusion": confusion_matrix(y_test, noisy_pred, labels=list(range(10))).tolist()})
            print(json.dumps({"step": "evaluate", "detail": f"seed={seed} {method} 训练与测试完成"}, ensure_ascii=False), flush=True)
            if seed == protocol["seeds"][0] and method == "improved":
                wrong = np.flatnonzero(noisy_pred != y_test)[:4]
                correct = np.flatnonzero(noisy_pred == y_test)[:4]
                for index in np.concatenate([correct, wrong]):
                    examples.append({"label": int(y_test[index]), "prediction": int(noisy_pred[index]),
                                     "clean": x_test[index].tolist(), "noisy": noisy_test[index].tolist()})
    aggregates = []
    for method in protocol["models"]:
        subset = [row for row in rows if row["method"] == method]
        aggregate = {"method": method}
        for key in ("cleanAccuracy", "noisyAccuracy", "cleanMacroF1", "noisyMacroF1", "fitSeconds"):
            values = [row[key] for row in subset]
            aggregate[key] = {"mean": float(np.mean(values)), "std": float(np.std(values, ddof=1))}
        aggregates.append(aggregate)
    by_method = {row["method"]: row for row in aggregates}
    gain = by_method["improved"]["noisyAccuracy"]["mean"] - by_method["baseline"]["noisyAccuracy"]["mean"]
    clean_change = by_method["improved"]["cleanAccuracy"]["mean"] - by_method["baseline"]["cleanAccuracy"]["mean"]
    augmentation_gain = by_method["improved"]["noisyAccuracy"]["mean"] - by_method["ablation"]["noisyAccuracy"]["mean"]
    criteria = protocol["acceptance"]
    accepted = gain >= criteria["minNoisyAccuracyGain"] and clean_change >= -criteria["maxCleanAccuracyDrop"]
    summary = f"相对线性基线，改进方法的带噪准确率变化 {gain * 100:+.2f} 个百分点，干净准确率变化 {clean_change * 100:+.2f} 个百分点。"
    summary += f"噪声增强相对相同 RBF 模型的变化为 {augmentation_gain * 100:+.2f} 个百分点。"
    summary += "达到预先设定的验证条件。" if accepted else "未达到预先设定的验证条件。"
    if augmentation_gain <= 0:
        summary += "本次结果不支持噪声增强优于无增强 RBF 模型。"
    output = {"protocolId": protocol["id"], "dataset": {"name": "sklearn digits", "samples": len(y), "features": x.shape[1],
              "sha256": hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()}, "splits": splits, "runs": rows, "aggregates": aggregates,
              "examples": examples, "verification": {"accepted": bool(accepted), "noisyAccuracyGain": gain,
              "cleanAccuracyChange": clean_change, "augmentationGain": augmentation_gain, "summary": summary,
              "limitation": "仅验证 8×8 手写数字及固定高斯噪声；3 次重复报告均值和样本标准差，不构成显著性检验。尚不能推广到真实相机图像、其他噪声或已有文献痛点。"},
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "sklearn": sklearn.__version__}}
    Path("result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:2000], "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr, flush=True)
        sys.exit(1)
