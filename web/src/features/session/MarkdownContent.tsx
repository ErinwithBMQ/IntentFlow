import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownContentProps = {
  children: string;
};

export function MarkdownContent({ children }: MarkdownContentProps) {
  return <Markdown remarkPlugins={[remarkGfm]}>{children}</Markdown>;
}
