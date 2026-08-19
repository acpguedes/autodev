# Auditoria do plano Beta — Gap Analysis (v2.0-beta)

> Escopo desta auditoria: **somente documentos** (MDs de `docs/`), conforme
> instrução. Nenhum código foi reavaliado; toda evidência abaixo cita
> documentos. Nada foi enviado a remoto (sem push/PR/merge).

## 1. Resumo executivo

**Fatos observados** (com evidência documental):

1. O gate v2.0-beta (§18.9) exige "fluxo real … validar em sandbox … com
   RBAC, budgets que falham fechado e traços fim a fim", mas **nenhum
   critério do gate exige isolamento fail-closed comprovado por evidência
   de execução** — o isolamento forte (classes, microVM) está integralmente
   em **E28 (v2.2)**, duas ondas depois do Beta.
   *Evidência:* `docs/architecture/v2_platform_reference.md` §18.9
   (v2.0-beta, critérios 1–9); `docs/v2_platform/phases/e28_execution_environments.md`.
2. **Secrets**: §16.1.2 define gestão de secrets, mas não há épico/história
   no recorte Beta que entregue store, injeção sem plaintext e redaction, e
   o gate Beta não menciona secrets.
   *Evidência:* §16.1.2; §18.9 (ausência); tabela de épicos em
   `docs/v2_platform/progress.md`.
3. **Instalação global**: E14 inclui `autodev` CLI install
   (`docs/execution/cli-install.md` previsto), mas não há estratégia de
   empacotamento/distribuição/upgrade, nem critério de gate de instalação
   em ambiente limpo.
   *Evidência:* `docs/v2_platform/phases/e14_real_execution_governance.md`;
   §18.9 (ausência).
4. Três decisões arquiteturais que mudam materialmente o escopo **não estão
   registradas como ADR**: backend de isolamento (container vs bubblewrap
   vs gVisor/microVM), formato do secret store e estratégia de instalação
   global. ADRs existentes vão até ADR-012.
   *Evidência:* `docs/v2_platform/decisions/` (ADR-001..012, RFC-001..008).

**Recomendações** (absorvidas neste plano):

- Criar o recorte Beta do ambiente isolado como épico próprio (**E32**),
  contrato-primeiro, com backend plugável e decisão pendente em ADR-013 —
  E28 (v2.2) evolui esse contrato em vez de introduzi-lo.
- Criar **E33** (secrets Beta: store, injeção, redaction; ADR-014 pendente)
  e **E34** (empacotamento/instalação/upgrade; ADR-015 pendente).
- Criar **E35** para transformar o gate Beta em gate com evidência mapeada,
  fluxo de aceitação executável e registro de decisões em aberto.
- Expandir os critérios de saída do v2.0-beta (§18.9) com isolamento
  fail-closed, secrets sem plaintext e instalação em ambiente limpo.

## 2. Tabela de lacunas

| # | Lacuna | Evidência (documento) | Resolução | Prioridade |
| --- | --- | --- | --- | --- |
| G1 | Gate Beta não exige isolamento comprovado; isolamento forte só em v2.2 (E28) | §18.9 v2.0-beta; `phases/e28_execution_environments.md` | E32 + critério (10) do gate | Alta |
| G2 | Fronteira E14×E28 sem recorte Beta definido para "onde roda" | `phases/e14_real_execution_governance.md` (runner contract E14-S4, sem camada de ambiente) | Seção "Relation to E14 and E28" em E32 | Alta |
| G3 | Secrets sem épico Beta (store, injeção, redaction) | §16.1.2; ausência em §18.9 e na tabela de épicos | E33 + critério (11) do gate | Alta |
| G4 | Instalação global sem estratégia de packaging/upgrade | `phases/e14_...md` (CLI UX apenas) | E34 + critério (12) do gate | Média |
| G5 | Critérios do gate sem mapa de evidência (auto-relato possível) | §18.9 (critérios sem fonte de evidência nomeada) | E35-S1 (mapa de evidência) | Média |
| G6 | Caminhos negativos (negação, budget, violação, revogação) fora da definição de aceitação Beta | §18.9 critério 1 (só caminho feliz) | E35-S2 | Média |
| G7 | Decisões arquiteturais materiais sem ADR (isolamento, secret store, instalação) | `decisions/` termina em ADR-012 | ADR-013/014/015 (Proposed, pendentes) + E35-S3 | Alta |
| G8 | Runbooks Beta de incidente (violação de isolamento, leak, upgrade falho) ausentes | conjunto de runbooks do E11 (`phases/e11_...md`) | E35-S3-T3 | Baixa |

## 3. Arquivos alterados/criados

Criados:
- `docs/v2_platform/beta_gap_analysis.md` (este documento)
- `docs/v2_platform/phases/e32_isolated_execution_beta.md`
- `docs/v2_platform/phases/e33_secrets_credential_governance.md`
- `docs/v2_platform/phases/e34_packaging_global_install.md`
- `docs/v2_platform/phases/e35_beta_readiness_gates.md`
- `docs/v2_platform/decisions/ADR-013-beta-isolation-backend.md` (Proposed)
- `docs/v2_platform/decisions/ADR-014-secret-store-format.md` (Proposed)
- `docs/v2_platform/decisions/ADR-015-global-install-strategy.md` (Proposed)

Editados:
- `docs/architecture/v2_platform_reference.md` (§18.9 v2.0-beta: Entra +
  critérios 10–12)
- `docs/v2_platform/phases/e14_real_execution_governance.md` (fronteira
  E32; CLI UX vs E34)
- `docs/v2_platform/phases/e11_observability_security_multitenant.md`
  (sinks de auditoria E32/E33, aditivo)
- `docs/v2_platform/phases/e12_quality_evals.md` (contract tests
  `execution_environment`, `secret_backend`)
- `docs/v2_platform/phases/e28_execution_environments.md` (consome o
  contrato E32; não bifurca)
- `docs/v2_platform/progress.md` (tabela de épicos + backlog E32–E35)
- `docs/v2_platform/decisions/README.md` (índice ADR-013/014/015)
- `docs/feature_matrix.md` (linhas E32–E35)

## 4. Mapa dos épicos novos (dependências e prioridade)

| Épico | Onda | Depende de | Habilita | Prioridade |
| --- | --- | --- | --- | --- |
| E32 — Isolated Execution Environment (Beta cut) | v2.0-beta | E14-S4, E0, E11 | E28 (v2.2), gate (10) | 1 |
| E33 — Secrets & Credential Governance | v2.0-beta | E11, E32, E0 | E14 com credenciais, gate (11) | 2 |
| E34 — Packaging & Global Install | v2.0-beta | E14 (CLI), E33-S1, E8 | gate (12), upgrade GA (E13) | 3 |
| E35 — Beta Readiness: Gates & Runbooks | v2.0-beta | E32, E33, E34, E11, E12 | gate mecânico, GA readiness | 4 |

Sequenciamento: E32-S1 e E33-S1 podem iniciar em paralelo (contratos);
E33-S2 depende de E32-S1; E34-S2 depende de E33-S1; E35 consolida ao final
mas E35-S1 (mapa de evidência) pode iniciar assim que os phase docs forem
aprovados.

## 5. Recorte Beta do ambiente isolado × E14 × E28

- **E14** define *o que* executa (tarefas, ações, política de
  permissão/aprovação, autonomia governada) e o contrato de runner
  (E14-S4).
- **E32 (novo, Beta)** define *onde* executa: abstração de ambiente com
  backend plugável, política fail-closed de rede/filesystem, ciclo de vida
  e auditoria. A escolha do backend é ADR-013 (pendente) — o Beta é
  implementável com o backend padrão atrás da abstração.
- **E28 (v2.2)** evolui o contrato de E32: classes `trusted`/`untrusted`,
  backends classe-microVM e machine snapshots. E28-S2 **consome** o
  contrato E32; não o substitui. O baseline de tempo de provisionamento
  medido em E32-S3 vira a referência de ganho do E28-S1.

## 6. Novos gates Beta (critérios adicionados ao §18.9 v2.0-beta)

- **(10)** Execução real ocorre em ambiente isolado fail-closed (E32):
  backend resolvido por política, negações tipadas e classe/perfil
  registrados em cada execução — comprovado por registros de run, não por
  configuração.
- **(11)** Nenhum secret em plaintext em prompts, logs, eventos, traces,
  diffs ou artefatos (E33): injeção só dentro do ambiente de execução;
  fixture de vazamento redigida e auditada.
- **(12)** Instalação em ambiente limpo documentada e verificada (E34):
  `autodev` operacional sem checkout do repositório, com versão reportada
  e upgrade entre duas versões preservando dados.

## 7. Registro de decisões em aberto (E35-S3-T1, atualizado 2026-08-19)

Nenhuma das três decisões abaixo permanece em aberto — todas foram
resolvidas **dentro do próprio épico** que as motivou, não silenciosamente:
cada ADR documenta a decisão e as consequências no próprio arquivo. Este
registro é mantido mesmo assim, como exigido por E35-S3-T1 — "no silent
resolution" significa que a decisão precisa estar rastreável com opções,
recomendação, dono e data, e está.

| Decisão | ADR | Opções | Recomendação | Dono | Decidir até | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Backend de isolamento Beta | [ADR-013](decisions/ADR-013-beta-isolation-backend.md) | container hardening; bubblewrap; gVisor; microVM | container hardening no Beta atrás da abstração; microVM em E28 | Epic owner (E32) | antes de E32-S2 | **Decidida** — Accepted 2026-08-18, container hardening (`HardenedContainerBackend`) |
| Formato do secret store | [ADR-014](decisions/ADR-014-secret-store-format.md) | arquivo cifrado; DB cifrado at rest; KMS/vault externo | DB cifrado at rest como default self-host; KMS como backend plugável | Epic owner (E33) | antes de E33-S2 | **Decidida** — Accepted 2026-08-18, SQLite cifrado (Fernet) atrás de `SecretBackendKind` |
| Estratégia de instalação global | [ADR-015](decisions/ADR-015-global-install-strategy.md) | pipx/uv tool; bundle container; script instalador | pipx/uv para CLI + bundle para self-host | Epic owner (E34) | antes de E34-S2 | **Decidida** — Accepted 2026-08-18, híbrido pip/pipx/uv + docker-compose |

`docs/v2_platform/decisions/README.md` ainda listava as três como
"Proposed" neste ponto — corrigido junto com esta atualização (drift de
doc, não uma decisão nova).

## 7.1 Registro de riscos Beta (E35-S3-T2)

| Risco | Impacto | Mitigação | Histórias | Status |
| --- | --- | --- | --- | --- |
| Escape de isolamento | Execução de código não confiável escapa do ambiente isolado, acessando o host ou rede não autorizada | Política default-deny de rede/filesystem, decisão auditada por execução, `UnavailableBackend` como kill switch de configuração; classe microVM mais forte é o alvo de E28 | E32-S2, E32-S4, E28 (v2.2) | Mitigado (Beta); defesa-em-profundidade adicional em E28 |
| Vazamento de secret | Valor de secret exposto em log, evento, trace, diff ou artefato | Redação de valor exato antes de qualquer persistência, aplicada dentro de `emit_event()` (protege todo produtor); evento `secret.leak.suspected` audita a tentativa | E33-S2, E33-S3 | Mitigado; detecção é exact-match apenas (sem heurística de entropia — limitação declarada) |
| Upgrade falho | Migração corrompe ou perde dados ao atualizar entre versões | Backup obrigatório antes de migrar (`BackupManager`); `MigrationRunner` recusa uma migração contra schema mais novo que o código conhece (`SchemaVersionMismatchError`); rollback via restore documentado | E34-S3, E8-S4 | Mitigado; sem ambiente de staging para ensaiar o restore (gap aberto, critério 6 do §11) |
| Execução descontrolada | Uma tarefa consome recursos/orçamento além do previsto, ou roda indefinidamente | Budgets que falham fechado no motor de raciocínio, política de execução por categoria, quotas por tenant, timeout de decisão pendente | E14-S2, E14-S3, E11-S3 | Mitigado |

Registro vivo — revisado a cada limite de onda (fim de v2.0-beta, início de
v2.1), ou sempre que um novo risco material for identificado.

## 8. Comandos de validação executados

Somente validações de documentação (escopo MD-only):
- `grep -rn "E3[2-5]" docs/ --include='*.md'` — antes: nenhuma ocorrência;
  depois: consistência entre phase docs, progress, feature matrix e §18.9.
- Verificação de links relativos citados nos docs novos (ver Task de
  verificação final no diff).
- `git status` / `git diff --stat` — diff final para revisão humana; sem
  push, merge ou PR.

## 9. Observação de honestidade do plano

Este plano **não** declara cobertura de "todos os conceitos SOTA". Ele
prioriza um Beta honesto e testável: fluxo central de coding completo
(plan → code → patch → validate → evaluate) com isolamento, secrets e
instalação comprováveis, e extensibilidade preservada (contratos + ADRs
pendentes explícitos) sem comprometer segurança, previsibilidade ou
qualidade.

## 10. Status de resolução das lacunas (E35, 2026-08-19)

E32, E33 e E34 foram implementados e mesclados a `main` (PRs #105, #106,
#107). Este parágrafo fecha o ciclo de auditoria aberto na Seção 2, sem
reescrever o registro histórico acima.

| # | Lacuna | Status | Como foi resolvida |
| --- | --- | --- | --- |
| G1 | Gate Beta não exige isolamento comprovado | **Resolvida** | Critério (10) do §18.9 (execução isolada fail-closed, backend/perfil auditado); evidência em §11 abaixo |
| G2 | Fronteira E14×E28 sem recorte Beta definido | **Resolvida** (já em E32) | `phases/e32_isolated_execution_beta.md` — seção de relação com E14/E28 |
| G3 | Secrets sem épico Beta | **Resolvida** | Critério (11) do §18.9 (referência escopada, redação, fixture de vazamento auditada); evidência em §11 |
| G4 | Instalação global sem estratégia de packaging/upgrade | **Resolvida** | Critério (12) do §18.9 (`autodev --version`, install limpo, upgrade com compatibility check); evidência em §11 |
| G5 | Critérios do gate sem mapa de evidência | **Resolvida** | Seção 11 abaixo — mapa de evidência para os 12 critérios do §18.9 v2.0-beta, com status honesto (Atendido/Parcial/Aberto) |
| G6 | Caminhos negativos fora da definição de aceitação Beta | **Resolvida** | `docs/v2_platform/beta_acceptance_flow.md` (E35-S2) |
| G7 | Decisões arquiteturais sem ADR | **Resolvida** | ADR-013/014/015 todos **Accepted** (ver Seção 7 atualizada, E35-S3) |
| G8 | Runbooks Beta de incidente ausentes | **Resolvida** | `docs/v2_platform/runbooks/e35_*.md` (E35-S3) |

## 11. Mapa de evidência do gate (§18.9 v2.0-beta) — E35-S1-T2

Disciplina fato vs. recomendação (E35-S1-T3): **Atendido** exige evidência
citável (teste, doc, registro de execução); **Parcial** significa evidência
real mas incompleta perante o critério; **Aberto** significa que nenhuma
evidência foi encontrada — é uma lacuna nomeada, não presumida como
resolvida.

| # | Critério (resumo) | Status | Evidência |
| --- | --- | --- | --- |
| 1 | Fluxo real plan→code→patch→validate→evaluate com RBAC, budgets fail-closed, traços fim a fim | **Parcial** | Cada componente tem evidência isolada — RBAC (`backend/tests/unit/security/`, ADR-018), budgets fail-closed (E14-S2 `backend/execution/policy.py` + E11-S3 quotas), traços (`test_orchestrator_agent_step_emits_correlated_span`), execução real (E14-S1..S4). **Sem um teste composto único** cobrindo os cinco passos numa mesma execução — esse é exatamente o objeto de `docs/v2_platform/beta_acceptance_flow.md` (E35-S2), que também não é um novo teste automatizado, é o checklist executável que compõe essa evidência. |
| 2 | Recuperação híbrida p95 < 300 ms e recall baseline | **Aberto** | `phases/e7_context_rag.md` linha 178 já declara: "unverified without a live [environment]". O harness existe (`backend/repository/retrieval/benchmark.py`, `scripts/benchmark_retrieval.py --max-p95-ms --min-recall`), mas não há execução registrada contra um ambiente vivo comprovando o alvo. |
| 3 | Streaming de run inicia < 1 s | **Aberto** | `backend/tests/unit/api/test_runs_stream_v2.py` cobre corretude funcional (backlog, resume, heartbeat, desconexão) mas nenhum teste mede um limite de latência numérico. |
| 4 | Todo ponto de extensão com contract test verde; quality gates bloqueiam merge | **Atendido** | `backend/tests/contract/test_extension_point_coverage.py`; `ci-backend.yml` (`lint-typecheck` + `patch-validation` gates, E12-S4) |
| 5 | UI WCAG 2.2 AA nas telas-chave; editor de fluxos com round-trip | **Parcial** | Round-trip: `frontend/lib/flow/yaml.ts` + E17-S6 (**Atendido**). WCAG: cobertura por componente via Storybook-axe em E15/E17 (`frontend/**/*.stories.tsx`), mas **nenhuma auditoria WCAG 2.2 AA consolidada por tela** existe — a auditoria de paridade visual E19 (proposta, não planejada) seria o veículo natural para isso. |
| 6 | Backup/restore validado (RPO ≤ 5 min, RTO ≤ 30 min) em staging | **Aberto** | `phases/e8_persistence_data.md` linhas 203–205: "No staging environment" — validação feita via procedimento de execução documentado (`runbooks/e8_restore_runbook.md`), não em staging real. |
| 7 | Linguagem de design v2 + app shell E15 adotados | **Atendido** | E15 Done (4/4); `docs/v2_platform/phases/e15_design_language_shell.md` |
| 8 | Paridade de API `/v2` (E16) | **Atendido** | E16 Done (4/4); `docs/v2_platform/phases/e16_redesign_api_enablement.md` |
| 9 | Telas do Control Center (E17) | **Atendido** | E17 Done (6/6); `docs/v2_platform/phases/e17_control_center_screens.md` |
| 10 | Execução isolada fail-closed por padrão, decisão auditada (E32) | **Atendido** | `backend/environments/` (`EnvironmentBackend`, `UnavailableBackend`), catálogo de eventos `environment.instance.*`/`environment.access.*`, `docs/environments/beta_isolation.md`, ADR-013 Accepted |
| 11 | Nenhum secret em claro; fixture de vazamento auditada (E33) | **Atendido** | `backend/secret_store/redaction.py`, evento `secret.leak.suspected`, `docs/security/secrets.md`, ADR-014 Accepted |
| 12 | Instalação em ambiente limpo verificada; upgrade preserva dados (E34) | **Atendido** | `scripts/verify_clean_install.sh`, `backend/ops/version.py`, `MigrationRunner.run_pending` (`SchemaVersionMismatchError`), `docs/execution/cli-install.md`, `docs/execution/upgrade.md`, ADR-015 Accepted |

**Resumo honesto**: 7 de 12 critérios **Atendidos** (4, 7, 8, 9, 10, 11,
12), 2 **Parciais** (1 e 5 — evidência real mas incompleta), 3 **Abertos**
(2, 3 e 6 — nenhuma evidência de verificação, apenas de
ferramentas/documentação para verificar). Isso não é o gate "completo" — é
o gate **mensurável**: cada
lacuna remanescente é nomeada com sua causa exata, não escondida atrás de
uma checkbox marcada. Fechar 2 e 6 exige um ambiente vivo (staging /
dataset de recuperação populado) que está fora do escopo de E35 (E35
audita e mapeia evidência; não é dono da infraestrutura de staging).
