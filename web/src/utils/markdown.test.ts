import { describe, expect, it } from 'vitest';

import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
  it('removes executable markup and hardens external links', () => {
    const container = document.createElement('div');
    container.innerHTML = renderMarkdown(
      '<img src="x" onerror="alert(1)"><script>alert(2)</script>\n\n[安全链接](https://example.com) [危险链接](javascript:alert(3))',
    );

    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')?.hasAttribute('onerror')).toBe(false);
    const links = container.querySelectorAll('a');
    expect(links).toHaveLength(2);
    expect(links[0]?.getAttribute('target')).toBe('_blank');
    expect(links[0]?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(links[1]?.hasAttribute('href')).toBe(false);
  });

  it('decorates fenced code blocks with their language', () => {
    const container = document.createElement('div');
    container.innerHTML = renderMarkdown('```ts\nconst ready = true;\n```');

    expect(container.querySelector('.code-block .code-header')?.textContent).toBe('ts');
    expect(container.querySelector('.code-block pre code')?.textContent).toContain(
      'const ready = true;',
    );
  });
});
