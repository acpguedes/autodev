# E17 — Pause Handoff (Control Center Screens)

> Estado congelado do épico E17 no momento da pausa solicitada pelo usuário.
> Todas as 6 story branches estão pushed em `origin`. Use este documento para retomar.

## Estado das branches

| Unit | Branch | Estado | Commit |
|------|--------|--------|--------|
| S1 Chat execution view | `story/e17-s1-chat-execution-view` | ✅ done | — |
| S2 Plans approval gates | `story/e17-s2-plans-approval-gates` | ⏸ WIP (typecheck quebrado) | `4c2a40d` |
| S3 Patches review | `story/e17-s3-patches-review` | ✅ done | `42b677a` |
| S4 Sessions & Config | `story/e17-s4-sessions-config` | ⏸ completo (só doc-polish) | `5ddfd81` |
| S5 Extensions hub | `story/e17-s5-extensions-hub` | ⏸ WIP (test/e2e não verificados) | `9da6c8b` |
| S6 Flow builder | `story/e17-s6-flow-builder` | ⏸ WIP (e2e quebrado) | wip pushed |

## Pendências por prioridade

### S2 — Plans approval gates (mais trabalho restante)

1. **Quebrado:** 2× `TS2322` em `lib/plans_v2.ts` (linhas 43,14 e 46,14).
   `EDITABLE_STEP_STATES`/`REMOVABLE_STEP_STATES` são `ReadonlySet<PlanStepState>` mas
   construídos com `new Set([...])` (inferido `Set<string>`).
   **Fix:** `new Set<PlanStepState>([...])`. Depois re-rodar `npm run typecheck`.
2. Rodar `npm run lint`, `npm run test`, `npm run build`, `make check-frontend` — nenhum rodado.
3. Criar e2e spec de `/plans` em `frontend/e2e/` — mock `**/v2/plans/**` via `page.route()`,
   seguindo o padrão de `shell-navigation.spec.ts`; cobrir load/edit/approve/reject/add/remove/execute.
4. Screen doc (provável `frontend/docs/screens/plans.md`, convenção não finalizada) + skill `code-review` no diff completo.
5. Commit final limpo (squash do wip) e push.
6. ⚠️ **Verificar backend:** `plan_approval_v2.py`, `events/catalog.py`, `step_state.py`,
   `test_plan_approval_v2.py` + 2 arquivos backend novos aparecem modificados no `git status`
   relativo ao tip do épico — o worker afirmou não ter tocado backend neste segmento; confirmar
   que nada está meio-terminado.
7. Higiene menor: `handleRemove` em `page.tsx` deixa entrada `true` stale em `stepBusy` após sucesso (inofensivo).

### S5 — Extensions hub

1. Trocar 5 locators `[role="button"]` → `[data-testid="extension-card"]` em
   `frontend/e2e/extensions-hub.spec.ts` (linhas ~159–202) — quebrados pela remoção do
   `role="button"` do `ExtensionCard`.
2. Re-rodar `npm run test`: 18 falhas anteriores (axe color-contrast, nested-interactive,
   `navModel.test.ts`) foram corrigidas mas **não verificadas**. Atenção especial ao padrão
   stretched-button novo (accessible-name) e efeitos do `pointer-events` restructuring.
3. `make check-frontend` e `npm run e2e` — nunca rodados neste esforço.
4. Commit/push de fixes adicionais na mesma branch.

### S6 — Flow builder

1. Debugar os 4 specs de `frontend/e2e/flow-builder.spec.ts` (todos falham):
   - Spec 1: `getByRole("heading", { name: "Flows library" })` não encontrado — inspecionar DOM real
     via `frontend/test-results/flow-builder-*/error-context.md`; pode ser markup sem heading role,
     warm-up do dev server, ou server cacheado servindo `FlowPalette.tsx` antigo (webServer reusa
     server existente fora de CI).
   - Specs 2–4 (botão `Coder`, `Clear`, `Save`): timeouts provavelmente em cascata do spec 1.
2. Re-rodar `npm run e2e` até verde.
3. Skill `code-review` + `make check-frontend` — não rodados.
4. Screen doc (provável adição curta em `docs/v2_platform/`).
5. Decidir se `NodeInspector.stories.tsx`/`FlowEditor.stories.tsx` são necessários.
6. Commit final (não-wip) e push.

### S4 — Sessions & Config (quase nada)

1. Doc-polish: em `docs/v2_platform/phases/e17_control_center_screens.md`, flagar explicitamente
   que o link reopen-as-chat `/?sessionId=<id>` do `SessionRow.tsx` **ainda não é consumido** por
   `frontend/app/page.tsx` (arquivo do E17-S1). Gap de integração cross-unit, não bug do S4.
2. **Ação de integração:** `app/page.tsx` precisa de `useSearchParams`/`sessionId` para o fluxo
   funcionar end-to-end — tratar no merge do épico ou fast-follow.
3. Verificação pré-pausa toda verde: 111/111 unit, 17/17 e2e, lint/typecheck/build limpos.

## Gotchas globais

- Playwright: `npx playwright install chromium` **sem** `--with-deps` (pede senha sudo no sandbox).
- `frontend/test-results/` **não** está gitignorado — não commitar (S6 deixou artefatos untracked no worktree).
- Token `--ds-fg-3`: mede 4.11:1 contra `--ds-bg-2` em dark mode (abaixo de 4.5:1 AA para body text);
  usos foram trocados por `text-ds-fg-2` em S5/S6, mas o token em si merece auditoria de design
  (comentário stale em `globals.css` linhas 130–133 referencia `frontend/docs/design-tokens.md` inexistente).
- `placeholder:text-ds-fg-3` deliberadamente mantido (axe não flagra contraste de placeholder).
- Sem `.claude/settings.json` nos worktrees → sem trailer `Co-Authored-By` (correto pela convenção do repo).

## Passos de retomada (ordem sugerida)

1. Retomar S2 (maior pendência) → S6 → S5 → S4 (doc-polish).
2. Integrar as 6 story branches na branch do épico (task #1 da sessão).
3. Gate pré-PR: save session, 85% check, frontend security audit (task #2).
4. PR do épico para `main`, merge, cleanup de branches, sync local (task #3).
5. No merge: resolver o gap S1↔S4 (`useSearchParams` em `app/page.tsx`).
