import { useEffect, useRef, useState } from "react";
import { api, canPreviewImage, pb, sessionGeneration } from "./api";
import type { Source } from "./types";
import "./evidence.css";

/** Remount the private image state whenever its source or signed-in identity changes. */
export default function ImagePreview({ source }: { source: Source }) {
  const [session, setSession] = useState(sessionGeneration);
  useEffect(() => pb.authStore.onChange(() => setSession(sessionGeneration)), []);
  if (!source.media_type.trim().toLowerCase().startsWith("image/")) return null;
  if (!canPreviewImage(source)) return <p>Preview is unavailable for this image format. Download the original to view it.</p>;
  if (!pb.authStore.isValid) return null;
  return <Preview key={`${session}:${source.id}:${source.original}`} source={source} />;
}

function Preview({ source }: { source: Source }) {
  const [actualSize, setActualSize] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [url, setURL] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const dialog = useRef<HTMLDialogElement>(null);
  const enlarge = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    let active = true;
    const generation = sessionGeneration;
    setURL(""); setStatus("loading");
    void api.previewURL(source).then(value => {
      if (active && generation === sessionGeneration && pb.authStore.isValid) setURL(value);
    }).catch(() => { if (active) setStatus("error"); });
    return () => { active = false; };
  }, [source.id, source.original, attempt]);
  const failed = () => {
    if (dialog.current?.open) dialog.current.close();
    setURL(""); setStatus("error");
  };
  return <figure className="image-preview" aria-label="Source image preview">
    {status === "loading" && <p role="status">Loading image preview…</p>}
    {status === "error" && <div><p role="alert">Unable to load image preview.</p><button onClick={() => setAttempt(value => value + 1)}>Retry image preview</button></div>}
    {url && <img src={url} alt={`Original source: ${source.title}`} onLoad={() => setStatus("ready")} onError={failed} hidden={status !== "ready"} />}
    {status === "ready" && <button className="image-enlarge" aria-haspopup="dialog" ref={enlarge} onClick={() => { setActualSize(false); dialog.current?.showModal(); }}>Enlarge image</button>}
    <dialog ref={dialog} className="image-preview-dialog" aria-label="Enlarged source image" onKeyDown={event => event.stopPropagation()} onClose={() => enlarge.current?.focus()}>
      <div className="image-preview-actions" role="group" aria-label="Image controls">
      <button autoFocus onClick={() => dialog.current?.close()}>Close enlarged image</button>
      <button aria-pressed={actualSize} onClick={() => setActualSize(value => !value)}>{actualSize ? "Fit image to width" : "Show actual size"}</button>
      </div>
      <div className={`image-preview-canvas${actualSize ? " actual-size" : ""}`} tabIndex={0} role="region" aria-label="Enlarged image; scroll to explore at actual size">{url && status === "ready" && <img src={url} alt={`Enlarged original source: ${source.title}`} onError={failed} />}</div>
    </dialog>
  </figure>;
}
