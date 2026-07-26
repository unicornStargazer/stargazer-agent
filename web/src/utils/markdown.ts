import DOMPurify from 'dompurify';
import { marked } from 'marked';

export function renderMarkdown(content: string): string {
  const parsedMarkdown = marked.parse(content, { async: false, breaks: true, gfm: true });
  const sanitizedHtml = DOMPurify.sanitize(parsedMarkdown, {
    USE_PROFILES: { html: true },
  });
  const documentFragment = new DOMParser().parseFromString(sanitizedHtml, 'text/html');
  secureLinks(documentFragment);
  decorateCodeBlocks(documentFragment);
  return documentFragment.body.innerHTML;
}

function secureLinks(documentFragment: Document): void {
  documentFragment.querySelectorAll('a').forEach((link) => {
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
  });
}

function decorateCodeBlocks(documentFragment: Document): void {
  documentFragment.querySelectorAll('pre').forEach((preformatted) => {
    const code = preformatted.querySelector('code');
    const languageClass = code
      ? [...code.classList].find((className) => className.startsWith('language-'))
      : undefined;
    const wrapper = documentFragment.createElement('div');
    wrapper.className = 'code-block';
    const header = documentFragment.createElement('div');
    header.className = 'code-header';
    header.textContent = languageClass?.replace('language-', '') ?? 'code';
    preformatted.replaceWith(wrapper);
    wrapper.append(header, preformatted);
  });
}
