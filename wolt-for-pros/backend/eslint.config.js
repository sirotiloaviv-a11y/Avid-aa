// ESLint flat config (ESLint 9+). Rules are listed explicitly so linting
// needs no packages beyond eslint itself.
const nodeGlobals = Object.fromEntries([
  'require', 'module', 'exports', '__dirname', '__filename', 'process', 'console', 'Buffer',
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate', 'clearImmediate',
  'URL', 'URLSearchParams', 'AbortController', 'fetch', 'structuredClone', 'TextEncoder', 'TextDecoder',
].map((name) => [name, 'readonly']));

module.exports = [
  { ignores: ['node_modules/**'] },
  {
    files: ['**/*.js'],
    languageOptions: { ecmaVersion: 2023, sourceType: 'commonjs', globals: nodeGlobals },
    linterOptions: { reportUnusedDisableDirectives: 'error' },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['error', { args: 'after-used', argsIgnorePattern: '^_|^next$', caughtErrors: 'none' }],
      'no-unreachable': 'error',
      'no-dupe-keys': 'error',
      'no-duplicate-case': 'error',
      'no-redeclare': 'error',
      'no-shadow-restricted-names': 'error',
      'no-self-assign': 'error',
      'no-self-compare': 'error',
      'no-cond-assign': 'error',
      'no-constant-condition': ['error', { checkLoops: false }],
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-fallthrough': 'error',
      'no-func-assign': 'error',
      'no-import-assign': 'error',
      'no-loss-of-precision': 'error',
      'no-unsafe-finally': 'error',
      'no-unsafe-negation': 'error',
      'no-unused-labels': 'error',
      'no-useless-catch': 'error',
      'no-var': 'error',
      'prefer-const': 'error',
      'eqeqeq': ['error', 'always', { null: 'ignore' }],
      'no-return-await': 'off',
      'require-atomic-updates': 'off',
      'no-async-promise-executor': 'error',
      'no-promise-executor-return': 'error',
      'use-isnan': 'error',
      'valid-typeof': 'error',
    },
  },
];
