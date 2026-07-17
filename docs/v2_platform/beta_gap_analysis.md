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

## 7. Riscos, decisões em aberto e ADRs/RFCs exigidos

| Decisão em aberto | ADR | Opções | Recomendação | Decidir até |
| --- | --- | --- | --- | --- |
| Backend de isolamento Beta | ADR-013 (Proposed) | container hardening; bubblewrap; gVisor; microVM | container hardening no Beta atrás da abstração; microVM em E28 | antes de E32-S2 |
| Formato do secret store | ADR-014 (Proposed) | arquivo cifrado; DB cifrado at rest; KMS/vault externo | DB cifrado at rest como default self-host; KMS como backend plugável | antes de E33-S2 |
| Estratégia de instalação global | ADR-015 (Proposed) | pipx/uv tool; bundle container; script instalador | pipx/uv para CLI + bundle para self-host | antes de E34-S2 |

Riscos principais: escape de isolamento (mitigado por E32-S2/S4 +
defesa-em-profundidade do E28), vazamento de secret (E33-S2/S3), upgrade
falho (E34-S3 + backup E8-S4), execução descontrolada (budgets E14 +
quotas E11). Registro vivo mantido por E35-S3.

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
