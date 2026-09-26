// Dependency-free ESLint flat config for the browser UI. Undefined-name checks
// are left to the TypeScript check (jsconfig.json), which knows the DOM types.
export default [
  {
    files: ["static/**/*.js"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module" },
    rules: {
      "no-unused-vars": ["error", { args: "none" }],
      "no-unreachable": "error",
      "no-dupe-keys": "error",
      "no-self-assign": "error",
      "prefer-const": "error",
      eqeqeq: ["error", "always"],
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-script-url": "error",
      // Model output must never become markup: build nodes with textContent.
      "no-restricted-properties": [
        "error",
        { property: "innerHTML", message: "Use textContent / DOM nodes." },
        { property: "outerHTML", message: "Use textContent / DOM nodes." },
        { property: "insertAdjacentHTML", message: "Use DOM nodes." },
        { object: "document", property: "write", message: "Use DOM nodes." },
      ],
    },
  },
];
