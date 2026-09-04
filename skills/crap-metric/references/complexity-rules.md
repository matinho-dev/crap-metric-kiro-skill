# Cyclomatic Complexity Rules by Language

Cyclomatic Complexity (CC) measures the number of linearly independent paths through a function's source code.

```
CC = 1 + (number of decision points)
```

Every function starts with a base complexity of **1**. Each branching or conditional decision point increases complexity by **+1**.

---

## Language Decision Points

### 1. Java (`.java`)
- `if`
- `else if` (counted as individual `if` branches)
- `for` (including enhanced `for (: )`)
- `while`
- `do ... while`
- `switch` / `case` (each `case` statement adds 1; `default` does not increment)
- `catch` (each exception handler adds an alternate control path)
- Logical operators: `&&`, `||`
- Conditional operator: `? :` (ternary)

### 2. Go (`.go`)
- `if`
- `for` (all forms: traditional, condition-only, infinite, range)
- `switch` / `case` (each `case` condition adds 1)
- `select` / `case` (each channel `case` adds an execution branch)
- Communication receive in case: `case <-ch:`
- Logical operators: `&&`, `||`

### 3. TypeScript / JavaScript (`.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`)
- `if`
- `else if`
- `for` (including `for ... of`, `for ... in`)
- `while`
- `do ... while`
- `switch` / `case`
- `catch`
- Logical operators: `&&`, `||`, `??` (nullish coalescing)
- Logical assignment operators: `&&=`, `||=`, `??=`
- Conditional operator: `? :` (ternary)
- Optional chaining (`?.`) is typically not counted unless expanding control flow branches.

### 4. PHP (`.php`)
- `if`
- `elseif` / `else if`
- `for`
- `foreach`
- `while`
- `do ... while`
- `switch` / `case`
- `match` / `case` (PHP 8+)
- `catch`
- Logical operators: `&&`, `||`, `and`, `or`, `xor`
- Null coalescing: `??`, `??=`
- Conditional operator: `? :` (ternary / Elvis `?:`)

### 5. Vue Single File Components (`.vue`)
Vue SFCs combine both markup template and code logic:
- `<template>` block:
  - `v-if` (+1)
  - `v-else-if` (+1)
  - `v-else` (+1)
  - `v-for` (+1)
- `<script>` / `<script setup>` block:
  - Follows standard **TypeScript / JavaScript** rules for all methods, computed properties, watchers, and hooks.

---

## Handling Preprocessing and Noise

To avoid false positives:
1. **Comments**: Strip all single-line (`//`, `#`) and multi-line (`/* ... */`) comments prior to counting keywords.
2. **String Literals**: Strip string literals (`"..."`, `'...'`, `` `...` ``, `<<<EOT`) so words like `"if"` inside log messages or SQL queries are ignored.
3. **Keyword Boundaries**: Use word boundary matching (`\bif\b`, `\bfor\b`) so variable names like `diff` or `verify` are not miscounted.
