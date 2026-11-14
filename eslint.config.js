import js from '@eslint/js';
import pluginVue from 'eslint-plugin-vue';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/', 'web/dist/', 'node_modules/', 'backend/', '.codex/', '.claude/'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['web/**/*.{ts,vue}'],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        parser: tseslint.parser,
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  {
    files: ['web/src/main.ts'],
    rules: {
      // TypeScript ESLint cannot infer Vue SFC module types; vue-tsc validates this import.
      '@typescript-eslint/no-unsafe-argument': 'off',
    },
  },
);
