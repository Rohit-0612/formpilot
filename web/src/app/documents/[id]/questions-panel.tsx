"use client";

import { type FormEvent, useState } from "react";

import { userMessage } from "@/lib/api/errors";
import {
  type Answer,
  type Question,
  type QuestionPart,
  useAnswersJob,
  useQuestions,
  useSubmitAnswers,
} from "@/lib/api/questions";

type Draft = {
  value: string;
  parts: Record<string, string>;
  freeText: string;
  oneLine: boolean;
  save: boolean;
  optIn: string[];
};

const EMPTY: Draft = { value: "", parts: {}, freeText: "", oneLine: false, save: false, optIn: [] };

function toAnswer(question: Question, draft: Draft): Answer | null {
  const base = {
    question_id: question.id,
    save_to_profile: draft.save,
    sensitive_opt_in: draft.save ? draft.optIn : [],
    parts: {},
  };
  if (question.free_text && draft.oneLine) {
    return draft.freeText.trim() ? { ...base, free_text: draft.freeText } : null;
  }
  if (question.parts.length === 1) {
    return draft.value.trim() ? { ...base, value: draft.value } : null;
  }
  const parts = Object.fromEntries(Object.entries(draft.parts).filter(([, v]) => v.trim()));
  return Object.keys(parts).length ? { ...base, parts } : null;
}

const inputClass =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none";

function PartInput({
  part,
  value,
  onChange,
  id,
}: {
  part: QuestionPart;
  value: string;
  onChange: (value: string) => void;
  id: string;
}) {
  if (part.input === "choice" || part.input === "yes_no") {
    const choices =
      part.input === "yes_no"
        ? [
            { value: "yes", label: "Yes, tick it" },
            { value: "no", label: "No, leave it empty" },
          ]
        : part.choices;
    return (
      <div className="flex flex-wrap gap-3">
        {choices.map((choice) => (
          <label key={choice.value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={id}
              value={choice.value}
              checked={value === choice.value}
              onChange={() => onChange(choice.value)}
            />
            {choice.label}
          </label>
        ))}
      </div>
    );
  }
  return (
    <input
      id={id}
      type={part.input === "date" ? "date" : "text"}
      autoComplete="off"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={inputClass}
    />
  );
}

function QuestionCard({
  question,
  draft,
  onChange,
}: {
  question: Question;
  draft: Draft;
  onChange: (draft: Draft) => void;
}) {
  const sensitive = question.parts.filter((p) => p.sensitive && p.semantic_type);
  const single = question.parts.length === 1;
  return (
    <fieldset className="rounded-lg border border-slate-200 bg-white p-4">
      <legend className="px-1 text-sm font-medium">{question.prompt}</legend>
      {question.form_text ? (
        <p className="mb-2 text-xs text-slate-500" lang="und">
          On the form: {question.form_text}
        </p>
      ) : null}
      {question.free_text ? (
        <label className="mb-3 flex items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={draft.oneLine}
            onChange={(event) => onChange({ ...draft, oneLine: event.target.checked })}
          />
          Type it in one line
        </label>
      ) : null}
      {question.free_text && draft.oneLine ? (
        <>
          <input
            aria-label={question.prompt}
            autoComplete="off"
            value={draft.freeText}
            onChange={(event) => onChange({ ...draft, freeText: event.target.value })}
            className={inputClass}
          />
          <p className="mt-1 text-xs text-slate-500">
            An AI model splits this line into the address parts. Leave out ID and phone numbers:
            text with one is not sent.
          </p>
        </>
      ) : single ? (
        <PartInput
          id={question.id}
          part={question.parts[0]}
          value={draft.value}
          onChange={(value) => onChange({ ...draft, value })}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {question.parts.map((part) => {
            const key = part.semantic_type ?? part.field_ids[0];
            return (
              <label key={key} className="text-xs text-slate-600">
                {part.label}
                {part.form_label ? (
                  <span className="block text-[11px] text-slate-400" lang="und">
                    On the form: {part.form_label}
                  </span>
                ) : null}
                <PartInput
                  id={`${question.id}-${key}`}
                  part={part}
                  value={draft.parts[key] ?? ""}
                  onChange={(value) => onChange({ ...draft, parts: { ...draft.parts, [key]: value } })}
                />
              </label>
            );
          })}
        </div>
      )}
      {question.can_save ? (
        <div className="mt-3 space-y-1 text-xs text-slate-600">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={draft.save}
              onChange={(event) => onChange({ ...draft, save: event.target.checked })}
            />
            Save to my profile for the next form
          </label>
          {draft.save
            ? sensitive.map((part) => {
                const key = part.semantic_type as string;
                return (
                  <label key={key} className="ml-5 flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={draft.optIn.includes(key)}
                      onChange={(event) =>
                        onChange({
                          ...draft,
                          optIn: event.target.checked
                            ? [...draft.optIn, key]
                            : draft.optIn.filter((k) => k !== key),
                        })
                      }
                    />
                    Also save my {part.label} (sensitive: stored encrypted, shown masked)
                  </label>
                );
              })
            : null}
        </div>
      ) : null}
    </fieldset>
  );
}

export function QuestionsPanel({ documentId }: { documentId: string }) {
  const questions = useQuestions(documentId, true);
  const submit = useSubmitAnswers(documentId);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useAnswersJob(documentId, jobId);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});

  if (questions.isPending) {
    return <p className="text-sm text-slate-500">Loading the questions…</p>;
  }
  if (questions.isError) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {userMessage(questions.error)}
      </p>
    );
  }
  const working = jobId !== null && (job.data?.status === "queued" || job.data?.status === "running");
  const list = questions.data.questions;
  if (list.length === 0) {
    return (
      <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
        Nothing left to ask: every field FormPilot can fill has a value.
      </p>
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const answers = list
      .map((q) => toAnswer(q, drafts[q.id] ?? EMPTY))
      .filter((a): a is Answer => a !== null);
    if (answers.length === 0) {
      return;
    }
    submit.mutate(answers, {
      onSuccess: (id) => {
        setDrafts({});
        setJobId(id);
      },
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <p className="text-sm text-slate-600">
        {list.length} {list.length === 1 ? "question" : "questions"} for{" "}
        {questions.data.fields_needing_input}{" "}
        {questions.data.fields_needing_input === 1 ? "field" : "fields"}. Answer any of them; the
        rest stay empty.
      </p>
      {list.map((question) => (
        <QuestionCard
          key={question.id}
          question={question}
          draft={drafts[question.id] ?? EMPTY}
          onChange={(draft) => setDrafts({ ...drafts, [question.id]: draft })}
        />
      ))}
      {submit.isError ? (
        <p role="alert" className="text-sm text-red-700">
          {userMessage(submit.error)}
        </p>
      ) : null}
      {job.data?.status === "failed" ? (
        <p role="alert" className="text-sm text-red-700">
          {job.data.error_message ?? "Your answers could not be used."}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={submit.isPending || working}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
      >
        {working || submit.isPending ? "Filling in your answers…" : "Send answers"}
      </button>
    </form>
  );
}
