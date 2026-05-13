module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
    'plugin:jsx-a11y/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs', 'node_modules', 'coverage'],
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  settings: { react: { version: '18.2' } },
  plugins: ['react-refresh', 'jsx-a11y'],
  rules: {
    'react-refresh/only-export-components': [
      'warn',
      { allowConstantExport: true },
    ],
    // The project doesn't use PropTypes — runtime prop validation isn't useful
    // without TypeScript, and the rule produces 100+ noise warnings.
    'react/prop-types': 'off',
    // Allow common React idioms with newer JSX runtime.
    'react/react-in-jsx-scope': 'off',
    // The label/control association rule misfires on group-of-buttons
    // patterns where the label sits next to a button-group rather than a
    // single input. The proper fix is fieldset/legend for those areas;
    // disable globally and re-enable case-by-case once that pass lands.
    'jsx-a11y/label-has-associated-control': 'off',
  },
  overrides: [
    {
      // Mathematical coefficients (GPS/Mercator transforms) use long literals
      // intentionally; flagging them as precision loss isn't actionable.
      files: ['src/utils/coordTransform.js'],
      rules: { 'no-loss-of-precision': 'off' },
    },
    {
      files: ['**/*.test.js', '**/*.test.jsx'],
      env: { node: true },
      rules: { 'no-unused-vars': 'off' },
    },
  ],
}
