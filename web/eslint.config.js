import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'src/api/schema.d.ts'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { react, 'react-hooks': reactHooks },
    languageOptions: { globals: globals.browser },
    settings: { react: { version: '18.3' } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Plan §10.4: stored content is text, never markup.
      'react/no-danger': 'error',
      'react/jsx-no-target-blank': 'error',
      'react/jsx-no-script-url': 'error',
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
    },
  },
);
