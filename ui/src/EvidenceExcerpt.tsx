import { Markdown } from "./Markdown";
import {
  AGENT_TEXT_LABEL,
  isAgentText,
  isMarkdownSource,
} from "./sourceRanges";
import type { Passage, Source } from "./types";

/** Marks evidence the user's agent derived from a non-text original. */
export function AgentTextLabel() {
  return <p className="agent-text-label">{AGENT_TEXT_LABEL}</p>;
}

export function EvidenceExcerpt({
  body,
  source,
  kind,
}: {
  body: string;
  source?: Pick<Source, "media_type" | "original_name">;
  kind?: Passage["kind"];
}) {
  const agentDerived = isAgentText({ kind });
  const derived =
    agentDerived ||
    Boolean(kind && kind !== "text") ||
    Boolean(
      source && !/^(text\/|application\/(json|xml))/.test(source.media_type),
    );
  // Agent text is Markdown only by its own conversion, not by the original's type.
  const excerpt =
    !derived && isMarkdownSource(source) ? (
      <div className="evidence-excerpt markdown">
        <Markdown body={body} mode="source" />
      </div>
    ) : (
      <pre className="evidence-excerpt source-text">{body}</pre>
    );
  return derived ? (
    <>
      {agentDerived ? (
        <AgentTextLabel />
      ) : (
        <p className="agent-text-label">Derived evidence — not an exact copy</p>
      )}
      {excerpt}
    </>
  ) : (
    excerpt
  );
}
