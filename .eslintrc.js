module.exports = {
  extends: 'next/core-web-vitals',
  rules: {
    '@typescript-eslint/no-unused-vars': ['warn', { 
      varsIgnorePattern: '^_', 
      argsIgnorePattern: '^_',
      ignoreRestSiblings: true 
    }]
  }
}; 