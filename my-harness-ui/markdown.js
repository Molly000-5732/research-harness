/* Local Markdown display only: original SDK replies remain unchanged in storage. */
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const normalize = value => String(value).replace(/\\/g, '/').replace(/\/$/, '');

  function resolveLink(raw, project, files = []) {
    if (!raw || /[\x00-\x1f]/.test(raw)) return null;
    let value = String(raw).trim();
    if (/^https?:\/\//i.test(value)) {
      try {
        const link = new URL(value);
        if (link.username || link.password) return null;
        return {href: link.href, external: true};
      } catch { return null; }
    }
    if (!project) return null;
    try { value = decodeURIComponent(value); } catch { return null; }
    const endpoint = `/api/projects/${project.id}/files/`;
    if (value.startsWith(endpoint)) value = value.slice(endpoint.length);
    value = normalize(value.replace(/^file:\/\/\//i, ''));
    const root = normalize(project.directory);
    const isWindows = /^[a-z]:\//i.test(root);
    const key = s => isWindows ? s.toLowerCase() : s;
    if (key(value).startsWith(key(root) + '/')) value = value.slice(root.length + 1);
    value = value.replace(/^\.\//, '');
    // Only registered project files become links. No arbitrary local/file URLs.
    const file = files.find(item => {
      if (key(normalize(item.path)) === key(value)) return true;
      // Markdown consumes backslashes before punctuation, e.g. \.research-harness.
      // Compare against each known file's parsed spelling; never guess a new path.
      if (!isWindows) return false;
      const absolute = String(project.directory).replace(/\/$/, '') + '\\' + item.path.replace(/\//g, '\\');
      const parsedSpelling = absolute.replace(/\\([^\w\s\u0080-\uFFFF]|_)/g, '$1');
      return key(normalize(parsedSpelling)) === key(value);
    });
    return file ? {href: endpoint + encodeURIComponent(file.path), download: file.name} : null;
  }

  function render(source, {project = null, files = []} = {}) {
    if (!window.marked || !window.DOMPurify) return `<div class="content">${escape(source)}</div>`;
    const renderer = new window.marked.Renderer();
    renderer.link = function({href, title, tokens}) {
      const label = this.parser.parseInline(tokens);
      const link = resolveLink(href, project, files);
      return link ? `<a href="${escape(link.href)}"${title ? ` title="${escape(title)}"` : ''}>${label}</a>`
        : `<span title="引用文件未在当前项目中找到，或链接不可用">${label}</span>`;
    };
    // Model-provided images must not cause background external requests.
    renderer.image = ({text}) => `<span>${escape(text)}</span>`;
    const parser = new window.marked.Marked({renderer, gfm: true, breaks: false});
    const fragment = window.DOMPurify.sanitize(parser.parse(String(source ?? '')), {
      RETURN_DOM_FRAGMENT: true,
      ALLOWED_TAGS: ['p','br','h1','h2','h3','h4','h5','h6','strong','em','del','ul','ol','li',
        'blockquote','pre','code','hr','table','thead','tbody','tr','th','td','a','span'],
      ALLOWED_ATTR: ['href','title','class','start','align'],
      ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false,
    });
    for (const anchor of fragment.querySelectorAll('a')) {
      const link = resolveLink(anchor.getAttribute('href'), project, files);
      if (!link) { anchor.removeAttribute('href'); continue; }
      anchor.setAttribute('href', link.href);
      if (link.external) {
        anchor.setAttribute('target', '_blank');
        anchor.setAttribute('rel', 'noopener noreferrer');
      } else anchor.setAttribute('download', link.download);
    }
    const wrapper = document.createElement('div');
    wrapper.append(fragment);
    return wrapper.innerHTML;
  }
  window.researchMarkdown = {render, resolveLink};
})();
