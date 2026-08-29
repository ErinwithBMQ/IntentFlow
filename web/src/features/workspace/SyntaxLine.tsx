import { Fragment } from "react";

import { tokenizeLine } from "./syntaxHighlight";

type SyntaxLineProps = {
  text: string;
  language: string;
};

export function SyntaxLine({ text, language }: SyntaxLineProps) {
  return tokenizeLine(text, language).map((token, index) => (
    <Fragment key={`${index}-${token.kind}`}>
      {token.kind === "plain"
        ? token.text
        : <span className={`syntax-token syntax-token--${token.kind}`}>{token.text}</span>}
    </Fragment>
  ));
}
