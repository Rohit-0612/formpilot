"use client";

import { useEffect, useRef, useState } from "react";

import {
  type IrField,
  type MaskedFormIR,
  type PageInfo,
  usePageImage,
} from "@/lib/api/documents";
import { userMessage } from "@/lib/api/errors";

type Kind = IrField["kind"];

// Full class names (Tailwind only sees literal strings).
const KIND_STYLE: Record<Kind, { box: string; swatch: string; name: string }> = {
  text: { box: "border-blue-600 bg-blue-500/10", swatch: "bg-blue-600", name: "Text" },
  checkbox: { box: "border-emerald-600 bg-emerald-500/10", swatch: "bg-emerald-600", name: "Checkbox" },
  radio: { box: "border-purple-600 bg-purple-500/10", swatch: "bg-purple-600", name: "Radio group" },
  choice: { box: "border-amber-600 bg-amber-500/10", swatch: "bg-amber-600", name: "Choice" },
  date: { box: "border-teal-600 bg-teal-500/10", swatch: "bg-teal-600", name: "Date" },
  signature: { box: "border-rose-600 bg-rose-500/10", swatch: "bg-rose-600", name: "Signature" },
  unknown: { box: "border-slate-600 bg-slate-500/10", swatch: "bg-slate-600", name: "Unknown" },
};

function percent(value: number, total: number): string {
  return `${(100 * value) / total}%`;
}

/** Position of an IR box (points, top-left of the displayed page) over the page image. */
function boxStyle(bbox: IrField["bbox"], page: PageInfo) {
  return {
    left: percent(bbox.x0, page.width),
    top: percent(bbox.y0, page.height),
    width: percent(bbox.x1 - bbox.x0, page.width),
    height: percent(bbox.y1 - bbox.y0, page.height),
  };
}

/** The field's printed label and kind. Values are never shown in Phase 2 (masked or not). */
function describe(field: IrField): string {
  const kind = KIND_STYLE[field.kind].name;
  return field.label_text ? `${field.label_text} · ${kind}` : kind;
}

function PageImage({ documentId, page }: { documentId: string; page: number }) {
  const image = usePageImage(documentId, page);
  const ref = useRef<HTMLImageElement>(null);

  // The object URL lives exactly as long as this effect: assigned through the ref (no state),
  // revoked on cleanup, so it is also correct when StrictMode runs effects twice.
  useEffect(() => {
    const element = ref.current;
    if (!image.data || !element) {
      return;
    }
    const url = URL.createObjectURL(image.data);
    element.src = url;
    return () => {
      element.removeAttribute("src");
      URL.revokeObjectURL(url);
    };
  }, [image.data]);

  if (image.isError) {
    return (
      <p role="alert" className="absolute inset-0 flex items-center justify-center p-4 text-sm text-red-700">
        {userMessage(image.error)}
      </p>
    );
  }
  return (
    <>
      {image.isPending ? (
        <p className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">
          Loading page…
        </p>
      ) : null}
      {/* A blob URL from an authenticated fetch: next/image cannot load it. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img ref={ref} alt={`Page ${page + 1}`} className="absolute inset-0 h-full w-full" />
    </>
  );
}

export function PageViewer({ documentId, ir }: { documentId: string; ir: MaskedFormIR }) {
  const [page, setPage] = useState(0);
  const info = ir.pages[page];
  const fields = (ir.fields ?? []).filter((field) => field.bbox.page === page);
  const kinds = [...new Set(fields.map((field) => field.kind))];

  return (
    <section aria-label="Page viewer">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage((p) => p - 1)}
            disabled={page === 0}
            className="rounded-md border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-100 disabled:opacity-40"
          >
            Previous
          </button>
          <span>
            Page {page + 1} of {ir.pages.length}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= ir.pages.length - 1}
            className="rounded-md border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-100 disabled:opacity-40"
          >
            Next
          </button>
        </div>
        <ul className="flex flex-wrap gap-3" aria-label="Legend">
          {kinds.map((kind) => (
            <li key={kind} className="flex items-center gap-1.5">
              <span className={`inline-block h-3 w-3 rounded-sm ${KIND_STYLE[kind].swatch}`} />
              {KIND_STYLE[kind].name} ({fields.filter((field) => field.kind === kind).length})
            </li>
          ))}
        </ul>
      </div>

      {info.text_layer !== "ok" ? (
        <p role="status" className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          This page has no usable text layer; its fields will be detected with OCR in a later
          version.
        </p>
      ) : fields.length === 0 ? (
        <p role="status" className="mb-3 text-sm text-slate-500">
          No fields were detected on this page.
        </p>
      ) : null}

      <div
        className="relative w-full overflow-hidden border border-slate-200 bg-white shadow-sm"
        style={{ aspectRatio: `${info.width} / ${info.height}` }}
      >
        <PageImage key={page} documentId={documentId} page={page} />
        {fields.map((field) => (
          <div key={field.id}>
            <div
              title={describe(field)}
              className={`absolute border-2 ${KIND_STYLE[field.kind].box}`}
              style={boxStyle(field.bbox, info)}
            />
            {field.kind === "radio"
              ? (field.options ?? []).map((option) =>
                  option.bbox ? (
                    <div
                      key={option.value}
                      title={option.label ?? option.value}
                      className="absolute border border-purple-800"
                      style={boxStyle(option.bbox, info)}
                    />
                  ) : null,
                )
              : null}
          </div>
        ))}
      </div>
    </section>
  );
}
