export type SyntaxTokenKind = "plain" | "comment" | "string" | "keyword" | "literal" | "number" | "operator" | "property";

export type SyntaxToken = {
  kind: SyntaxTokenKind;
  text: string;
};

const KEYWORDS: Record<string, Set<string>> = {
  javascript: new Set([
    "async", "await", "break", "case", "catch", "class", "const", "continue", "default",
    "delete", "do", "else", "export", "extends", "finally", "for", "from", "function",
    "if", "import", "in", "instanceof", "let", "new", "of", "return", "static", "switch",
    "throw", "try", "typeof", "var", "void", "while", "yield",
  ]),
  typescript: new Set([
    "abstract", "as", "async", "await", "break", "case", "catch", "class", "const",
    "continue", "declare", "default", "delete", "do", "else", "enum", "export", "extends",
    "finally", "for", "from", "function", "if", "implements", "import", "in", "instanceof",
    "interface", "keyof", "let", "namespace", "new", "of", "private", "protected", "public",
    "readonly", "return", "satisfies", "static", "switch", "throw", "try", "type", "typeof",
    "var", "void", "while", "yield",
  ]),
  python: new Set([
    "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
    "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in",
    "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while",
    "with", "yield",
  ]),
  html: new Set([
    "a", "aside", "body", "button", "code", "div", "footer", "form", "head", "header",
    "html", "input", "label", "li", "link", "main", "meta", "nav", "ol", "p", "script",
    "section", "span", "strong", "style", "title", "ul",
  ]),
};

const LITERALS = new Set(["false", "null", "true", "undefined", "False", "None", "True"]);
const OPERATOR_CHARACTERS = new Set("{}[]()<>.:,;=+-*/%!&|?@".split(""));

function appendToken(tokens: SyntaxToken[], kind: SyntaxTokenKind, text: string) {
  if (!text) return;
  const previous = tokens.at(-1);
  if (previous?.kind === kind) {
    previous.text += text;
  } else {
    tokens.push({ kind, text });
  }
}

function isIdentifierStart(character: string): boolean {
  return /[A-Za-z_$]/.test(character);
}

function isIdentifierPart(character: string): boolean {
  return /[\w$-]/.test(character);
}

function commentPrefixAt(line: string, index: number, language: string): string | null {
  if (language === "html" && line.startsWith("<!--", index)) return "<!--";
  if (["python", "shell", "yaml"].includes(language) && line[index] === "#") return "#";
  if (["javascript", "typescript", "css"].includes(language) && line.startsWith("//", index)) {
    return "//";
  }
  if (["javascript", "typescript", "css"].includes(language) && line.startsWith("/*", index)) {
    return "/*";
  }
  return null;
}

export function tokenizeLine(line: string, language: string): SyntaxToken[] {
  if (language === "text" || language === "markdown") return [{ kind: "plain", text: line }];

  const tokens: SyntaxToken[] = [];
  const keywords = KEYWORDS[language] ?? new Set<string>();
  let index = 0;

  while (index < line.length) {
    const commentPrefix = commentPrefixAt(line, index, language);
    if (commentPrefix) {
      appendToken(tokens, "comment", line.slice(index));
      break;
    }

    const character = line[index];
    if (character === '"' || character === "'" || character === "`") {
      const quote = character;
      let end = index + 1;
      while (end < line.length) {
        if (line[end] === "\\") {
          end += 2;
          continue;
        }
        if (line[end] === quote) {
          end += 1;
          break;
        }
        end += 1;
      }
      appendToken(tokens, "string", line.slice(index, end));
      index = end;
      continue;
    }

    if (/\d/.test(character)) {
      const match = line.slice(index).match(/^\d+(?:\.\d+)?/);
      const value = match?.[0] ?? character;
      appendToken(tokens, "number", value);
      index += value.length;
      continue;
    }

    if (isIdentifierStart(character)) {
      let end = index + 1;
      while (end < line.length && isIdentifierPart(line[end])) end += 1;
      const value = line.slice(index, end);
      const remainder = line.slice(end).trimStart();
      const kind = keywords.has(value)
        ? "keyword"
        : LITERALS.has(value)
          ? "literal"
          : (["css", "json", "yaml"].includes(language) && remainder.startsWith(":"))
            ? "property"
            : "plain";
      appendToken(tokens, kind, value);
      index = end;
      continue;
    }

    if (OPERATOR_CHARACTERS.has(character)) {
      appendToken(tokens, "operator", character);
    } else {
      appendToken(tokens, "plain", character);
    }
    index += 1;
  }

  return tokens;
}
