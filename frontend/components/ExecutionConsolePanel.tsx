"use client";

import type { RunResponse } from "../lib/api";

type ExecutionConsolePanelProps = {
  runs: RunResponse[];
  isBusy: boolean;
};

type ConsoleEntry = {
  id: string;
  label: string;
  command: string;
  output: string;
  status: string;
};

function buildConsoleEntries(runs: RunResponse[]): ConsoleEntry[] {
  return runs.flatMap((run) =>
    run.results.map((result, index) => {
      const taskTitle =
        typeof result.metadata?.title === "string" ? result.metadata.title : result.content;
      const taskDescription =
        typeof result.metadata?.description === "string"
          ? result.metadata.description
          : result.content;
      const category =
        typeof result.metadata?.category === "string" ? result.metadata.category : result.agent;
      const sourceAgent =
        typeof result.metadata?.source_agent === "string"
          ? result.metadata.source_agent
          : result.agent;
      const status =
        typeof result.metadata?.status === "string" ? result.metadata.status : run.status;

      return {
        id: `${run.run_id}-${index}`,
        label: run.run_type === "plan_execution" ? "Execução" : "Agente",
        command:
          run.run_type === "plan_execution"
            ? `${category}: ${taskTitle}`
            : `${sourceAgent} -> ${taskTitle}`,
        output: taskDescription,
        status,
      };
    })
  );
}

export function ExecutionConsolePanel({ runs, isBusy }: ExecutionConsolePanelProps) {
  const entries = buildConsoleEntries(runs);

  return (
    <aside className="execution-console" aria-live="polite">
      <div className="execution-console__header">
        <div>
          <p className="eyebrow">Execução</p>
          <h2>Painel lateral</h2>
        </div>
        <span className={`status-pill ${isBusy ? "status-pill--running" : ""}`}>
          {isBusy ? "Executando" : "Pronto"}
        </span>
      </div>

      <p className="status-text">
        {isBusy
          ? "Mostrando a atividade mais recente, comandos derivados e saídas registradas."
          : "Quando houver atividade, o histórico executado aparece aqui em ordem cronológica."}
      </p>

      {entries.length === 0 ? (
        <div className="execution-console__empty">
          <p>Ainda não há comandos ou saídas registrados para esta sessão.</p>
        </div>
      ) : (
        <div className="execution-console__stream">
          {entries.map((entry) => (
            <article className="console-entry" key={entry.id}>
              <div className="console-entry__header">
                <span className="console-entry__label">{entry.label}</span>
                <span className="status-pill">{entry.status}</span>
              </div>
              <code className="console-entry__command">{entry.command}</code>
              <pre className="console-entry__output">{entry.output}</pre>
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}

export default ExecutionConsolePanel;
