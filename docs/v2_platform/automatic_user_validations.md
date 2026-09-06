# Validações de aceitação do usuário

> Roadmap vivo das jornadas de aceitação executadas no frontend do AutoDev.
> Este documento define o que testar, por que o teste importa, quais evidências
> coletar e como registrar resultados e melhorias. Ele não substitui testes
> unitários, de integração, de acessibilidade, segurança ou desempenho.

**Última atualização:** 2026-09-06 — `U01` executed as `BLOCKED`; 1 case is
`PASS`, 2 are `FAIL`, 1 is `BLOCKED`, and 37 remain `NOT_RUN`.

## 1. Objetivo e autoridade

Este roteiro valida o produto pela interface visível, do ponto de vista de uma
pessoa usuária. Cada conclusão deve estar sustentada por comportamento observado
na versão instalada e por evidências reais. Inspeção de código pode ajudar a
investigar um achado depois da campanha, mas nunca substitui a execução do caso.

Este arquivo é a fonte canônica para:

- escopo, prioridade, dependências e critérios dos casos `F01`–`U07`;
- estado e resultado das execuções;
- evidências, limitações de comprovação e resíduos de teste;
- correções ou melhorias inferidas a partir do comportamento observado.

`docs/v2_platform/progress.md` continua sendo a fonte canônica do estado da
implementação v2. Quando uma validação revelar divergência entre experiência,
documentação e implementação, atualize os documentos afetados no mesmo conjunto
de mudanças, sem declarar uma hipótese como fato.

## 2. Princípios de execução

1. Use exclusivamente controles e informações visíveis na UI: cliques,
   digitação, rolagem, teclado e navegação normal.
2. Não use shell, APIs diretas, banco, código-fonte, JavaScript injetado, mocks
   ou edição externa para completar uma jornada.
3. Faça um caso por vez. Casos de raciocínio independentes usam sessões novas.
4. Não corrija o produto durante a campanha. Preserve primeiro as evidências e
   separe observação, impacto e hipótese de causa.
5. Toast, resposta do agente, botão habilitado ou aparência de sucesso não
   comprovam persistência, mutação ou execução. Verifique o artefato em `Files`,
   o diff, o log ou a persistência após reload quando o caso exigir.
6. Limite cada caso a 5 minutos e casos dependentes de LLM/execução a 10 minutos.
   Sem progresso verificável, registre `BLOCKED` por timeout de observação; não
   atribua falha ao backend sem evidência.
7. Faça no máximo uma repetição controlada para reprodução. Antes de repetir uma
   mutação, confira se a primeira tentativa já produziu efeito.
8. Altere apenas fixtures QA descartáveis. Preserve evidências antes de limpar e
   restaure configurações temporárias pela UI.
9. O YAML só pode ser editado no campo visível nos casos `F08` e `F09`. Ele não
   pode ser usado para contornar outra jornada.
10. Nunca exponha credenciais, segredos ou dados alheios nas evidências.
11. Antes de despachar qualquer caso à Astra, verifique se o ambiente alvo
    carrega: URL do frontend responde, backend acessível e workspace citado
    existe. Se houver bloqueio, resolva-o você mesmo por meios não destrutivos
    e já documentados (por exemplo, `make run`/`make run-backend`/
    `make run-frontend`) ou instrua o usuário com a ação exata necessária;
    nunca despache um caso contra um ambiente que não carrega. Não modifique
    código ou configuração para destravar o ambiente — apenas operações
    documentadas de start/restart. Registre a verificação e, se houve
    bloqueio, o que foi feito para destravá-lo.
12. Execute cada comando de diagnóstico ou orquestração exatamente uma vez;
    repita apenas quando a tentativa anterior tiver falhado ou o estado do
    ambiente tiver mudado. Mantenha entradas e saídas trocadas com o ambiente
    enxutas — capture só o necessário para decidir o próximo passo.

## 3. Estados, prioridade e classificação

### Estado do caso

| Estado | Semântica |
| --- | --- |
| `PASS` | Todos os critérios relevantes foram observados e sustentados por evidências. |
| `FAIL` | A observação contradiz um critério, inclusive quando falta uma capacidade desejada. |
| `BLOCKED` | Uma pré-condição está ausente ou não há observabilidade suficiente para comprovar o resultado. |
| `NOT_RUN` | O caso ainda não foi tentado. Não usar para uma tentativa bloqueada. |

### Prioridade do teste

| Prioridade | Uso |
| --- | --- |
| `P0` | Jornada central, autorização, integridade ou comprovação essencial. |
| `P1` | Robustez, recuperação, consistência ou fricção relevante. |
| `P2` | Refinamento de experiência e qualidade de uso. |

Prioridade do teste não é severidade do achado. Classifique o achado separadamente
como `bug funcional`, `lacuna de funcionalidade`, `UX`, `observabilidade` ou
`ambiente`, com severidade:

- `S0`: execução sem autorização, workspace errado, segredo exposto ou perda
  grave de dados;
- `S1`: jornada central impossível ou falso sucesso de execução/persistência;
- `S2`: comportamento parcial, perda de rascunho ou fricção relevante com
  alternativa viável;
- `S3`: problema visual ou textual menor.

## 4. Preparação da campanha

Antes de qualquer item abaixo, aplique o princípio 11: confirme que a URL do
frontend carrega sem erro de conexão, que o backend responde e que o
workspace citado existe. Resolva bloqueios com meios não destrutivos ou
instrua o usuário antes de prosseguir.

Antes do primeiro caso, registre:

- URL do frontend, commit/build realmente instalado, navegador, viewport,
  timezone e autenticação;
- workspace QA descartável com `README.md` conhecido, uma pasta com arquivo de
  texto e escrita limitada ao escopo do teste;
- segundo workspace QA vazio para `C06`;
- provider/modelo reais para raciocínio e execução; se houver stub, registre-o:
  stub comprova somente a UI, não o comportamento real do agente;
- modo Approval e planos/runs identificáveis para `E01`–`E03` e `P01`;
- configurações iniciais, IDs das fixtures e um `RUN` exclusivo contendo apenas
  letras minúsculas, números e hífens, por exemplo `20260906-a1`.

Dependências: `C04` usa o arquivo de `C03`; `C05` pode usar fixture equivalente;
`A02` e `A03` dependem de `A01` ou de agente QA preparado. Falha de setup deve
bloquear os casos dependentes, não virar várias falhas do produto.

## 5. Prompt-base da campanha

Acrescente à instrução somente os casos do lote, com URL, RUN e fixtures
preenchidos.

```text
Teste o AutoDev como usuário final, usando exclusivamente a interface visível.
URL: <URL>
Versão/build: <versão ou desconhecida>
RUN: <identificador>
Workspace autorizado: <workspace QA>
Casos deste lote: <IDs e especificações deste documento>

Execute um caso por vez e respeite pré-condições, passos e critérios.
Não use shell, APIs diretas, banco, código-fonte, JavaScript injetado, estado
interno, mocks ou edição externa. Não corrija o produto durante a campanha.

Antes de agir, registre URL, fixture, sessão/run e estado inicial. Capture
evidência após a ação e no estado final. Para falhas, registre a mensagem exata
e os passos mínimos de reprodução. Não infira ações ocultas e não marque PASS
apenas por toast, resposta do agente ou aparência de botão.

Classifique o caso como PASS, FAIL, BLOCKED ou NOT_RUN. Classifique o achado
separadamente. Separe observações de hipóteses. Não crie issues nem publique
mensagens. Entregue resultados por caso, achados deduplicados, correções ou
melhorias propostas, bloqueios, limitações e resíduos.
```

## 6. Roadmap e ordem de execução

Lote inicial de alto valor:

`U01 → U03 → F01 → F02 → A01 → C01 → C03 → C04 → C09 → E04`

Depois execute, nesta ordem geral:

1. demais casos de Flows e Extensions;
2. leitura, escrita e Routing;
3. revisão, permissões e aprovações;
4. sessões, acompanhamento e reconexão;
5. configuração, UX e resiliência.

Se `F01` falhar, continue `F03`–`F11` com flow temporário. Se provider real não
estiver disponível, continue casos de UI independentes dele. Se uma ação cruzar
uma aprovação ou atingir workspace incorreto, interrompa mutações relacionadas,
preserve a evidência e prossiga somente com inspeção segura.

### Catálogo executivo

| ID | Pri. | Área | O que será testado | Objetivo/impacto | Coleta principal | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | P0 | Flows | Criar e persistir flow mínimo | Provar a jornada central de autoria | Canvas, Save, catálogo após reload | FAIL |
| F02 | P0 | Flows | Abrir flow registrado | Provar reuso e continuidade | Item e editor resultante | FAIL |
| F03 | P1 | Flows | Editar propriedade de nó | Garantir consistência editor/canvas | Inspector e canvas antes/depois | PASS |
| F04 | P1 | Flows | Renomear nó conectado | Preservar referências do grafo | ID, arestas e Issues | NOT_RUN |
| F05 | P1 | Flows | Recusar ID duplicado | Evitar grafo ambíguo | Entrada, feedback e valor efetivo | NOT_RUN |
| F06 | P1 | Flows | Excluir nó conectado | Manter integridade estrutural | Canvas e Issues antes/depois | NOT_RUN |
| F07 | P1 | Flows | Bloquear flow inválido | Evitar falso salvamento | Campo inválido, erro e recuperação | NOT_RUN |
| F08 | P1 | Flows | Sincronizar visual e YAML | Provar edição bidirecional sem perda | Inspector, YAML e canvas | NOT_RUN |
| F09 | P1 | Flows | Recuperar YAML inválido | Provar erro seguro e reversível | YAML, Issues e grafo recuperado | NOT_RUN |
| F10 | P1 | Flows | Pré-visualizar aprovação humana | Tornar destinos de decisão claros | Prompt, opções e destinos | NOT_RUN |
| F11 | P1 | Flows | Proteger edição não salva | Evitar perda silenciosa | Alteração, aviso e retorno | NOT_RUN |
| A01 | P0 | Extensions | Criar agente mínimo | Provar autoria e persistência | Formulário, catálogo e detalhe | NOT_RUN |
| A02 | P1 | Extensions | Editar agente existente | Evitar duplicação e perda de identidade | ID, nome e contagem | NOT_RUN |
| A03 | P1 | Extensions | Desativar e reativar agente | Provar controle de ciclo de vida | Switch, badge e reloads | NOT_RUN |
| A04 | P1 | Extensions | Validar formulário obrigatório | Impedir extensão parcial/inválida | Erros e catálogo | NOT_RUN |
| A05 | P2 | Extensions | Inspecionar catálogo por tipo | Avaliar clareza e consistência | Abas, cartões e detalhes | NOT_RUN |
| C01 | P0 | Chat | Pedido sem ferramentas | Evitar execução desnecessária | Turno, resposta e timeline | NOT_RUN |
| C02 | P0 | Chat | Ler arquivo sem modificar | Provar grounding com segurança | Arquivo, resposta, patches/logs | NOT_RUN |
| C03 | P0 | Chat | Criar exatamente um arquivo | Provar execução e artefato real | Pedido, gates, diff e Files | NOT_RUN |
| C04 | P0 | Chat | Editar exatamente uma linha | Provar mudança mínima | Diff e conteúdo final | NOT_RUN |
| C05 | P0 | Routing | Não estruturar uma edição simples | Provar roteamento proporcional | Seleção, justificativa e diff | NOT_RUN |
| C06 | P1 | Routing | Escolher flow para projeto novo | Provar adequação de planejamento | Workspace, seleção e plano | NOT_RUN |
| C07 | P1 | Routing | Fallback sem flow específico | Evitar flow alheio | Catálogo, resposta e ações | NOT_RUN |
| C08 | P1 | Chat | Bloquear envio vazio/duplicado | Evitar turnos inválidos ou duplicados | Composer, histórico e contagem | NOT_RUN |
| C09 | P0 | Chat | Reabrir conversa persistida | Provar durabilidade da sessão | IDs e histórico antes/depois | NOT_RUN |
| C10 | P1 | Chat | Isolar duas sessões | Evitar mistura de contexto | IDs, mensagens, planos e runs | NOT_RUN |
| E01 | P0 | Governança | Respeitar rejeição de passo | Impedir ação rejeitada | Estado, Files e log | NOT_RUN |
| E02 | P0 | Governança | Aprovar uma vez e retomar | Provar escopo e retomada corretos | Decisão, IDs, log e artefato | NOT_RUN |
| E03 | P0 | Governança | Negar ação pendente | Impedir efeito e falso sucesso | Decisão, log e Files | NOT_RUN |
| E04 | P1 | Execution | Acompanhar execução ao vivo | Provar feedback e estado coerentes | Início, meio, fim, IDs e mensagens | NOT_RUN |
| E05 | P1 | Execution | Reconectar após reload | Provar continuidade sem duplicação | IDs, timeline e artefato | NOT_RUN |
| E06 | P1 | Execution | Exibir falha sem falso sucesso | Provar propagação de erro | Comando, código, saída e estado | NOT_RUN |
| P01 | P0 | Patches | Revisar mudança antes de aplicar | Preservar controle humano | Diff, aprovação e original | NOT_RUN |
| P02 | P0 | Files | Navegar árvore e conteúdo | Provar identidade correta do arquivo | Árvore, caminho e trechos | NOT_RUN |
| U01 | P0 | Navegação | Abrir telas principais | Detectar quebra estrutural | URL, captura e erro por tela | NOT_RUN |
| U02 | P1 | Config | Persistir opção não secreta | Provar configuração reversível | Valor original/alterado/restaurado | NOT_RUN |
| U03 | P0 | Config | Identificar provider real/stub | Evitar evidência enganosa | Indicadores e campos não secretos | NOT_RUN |
| U04 | P1 | UX | Usar painel em tela estreita/zoom | Garantir acesso aos controles | Viewports, zoom e capturas | NOT_RUN |
| U05 | P2 | UX | Operar formulário por teclado | Avaliar foco e navegação | Teclas e foco visível | NOT_RUN |
| U06 | P2 | UX | Alternar tema e idioma | Avaliar legibilidade e tradução | Capturas e strings inconsistentes | NOT_RUN |
| U07 | P1 | Resiliência | Preservar texto na indisponibilidade | Evitar perda/duplicação na recuperação | Texto, erro e histórico | NOT_RUN |

## 7. Casos detalhados

Em todos os casos, o registro de resultado começa como `NOT_RUN`. Após a
execução, preencha a linha correspondente na seção 8 e acrescente evidências e
achados na subseção do caso quando isso melhorar a rastreabilidade.

### Flows

#### F01 — Criar e persistir um flow mínimo (P0)

- **Instrução Astra:** `Create one simple flow using only the visible UI and confirm that it appears in the flows list.`
- **Pré-condição:** UI acessível; nenhum flow de teste aberto.
- **Procedimento:** Flows → New blank flow; defina `QA-{RUN}-simple` por controles
  visuais; adicione Start → agente disponível → End; use Save; procure a entrada;
  recarregue.
- **PASS:** nome próprio, grafo válido e entrada persistida no catálogo após
  reload. Download isolado não satisfaz o caso.
- **Coletar:** canvas antes de salvar, mensagem posterior, eventual download e
  catálogo após reload.
- **Impacto:** sem persistência e reabertura, autoria de flows não é uma jornada
  utilizável. Se não existir controle visual para nomear, registre lacuna; não use
  YAML como substituto.

**Execution `20260906-f01a` (2026-09-06, America/Bahia):**

- Environment: `http://localhost:3000`, base commit `5a011fe`, Chromium through
  Playwright MCP, 1280×720 capture viewport, no authentication, and the default
  stub provider (not material to this persistence-only case).
- Result: `FAIL` in 2m12s. Astra session
  `01a074d5-ed65-7872-90a4-9ef02a570f92` created Start → Planner → End, but
  Save registered `autodev/flow-untitled@0.1.0`; no visible naming control was
  available. Reload persistence could not be evaluated for the required named
  artifact.
- Diagnostic residue: before the documentation-only boundary was clarified, a
  temporary, uncommitted naming-control experiment was exercised by the exact
  journey. It passed in 2m07s in Astra session
  `01a074d9-e495-7f80-bc84-0496637effec`, but the experiment was fully reverted
  and is not part of this delivery or evidence that the current build passes.
- Evidence limitation: browser screenshots were blank and are not cited as
  proof. The structured observations, exact visible text, journey, sessions,
  and finding are preserved in this Markdown report. No separate browser run id
  was exposed.
- Residue: `autodev/flow-untitled@0.1.0` and
  `autodev/qa-20260906-f01a-simple@0.1.0` remain in the local QA registry; no
  settings were changed and no run remains active.

#### F02 — Abrir um flow registrado (P0)

- **Instrução Astra:** `Open one existing flow from the flows list using the UI and inspect its nodes.`
- **Pré-condição:** catálogo com ao menos um flow registrado.
- **Procedimento:** selecione o item; procure ação de abrir/editar; confira
  identidade, versão e nós.
- **PASS:** o item escolhido abre com nome, versão e grafo correspondentes.
- **Coletar:** catálogo, item escolhido e editor após a tentativa.
- **Impacto:** valida continuidade e manutenção. Catálogo vazio é `BLOCKED`.

**Execution `20260906-f02a` (2026-09-06, America/Bahia):**

- Environment: `http://localhost:3000`, base commit `723fd739`, Chromium through
  Playwright MCP, no authentication, with the catalog precondition documented by
  the residual F01 QA flows.
- Result: `BLOCKED` in 1m03s. Astra session
  `01a074fb-3dd2-7873-8590-8a2ec404da55` could not load the application: the
  browser showed `This site can’t be reached`, `localhost refused to connect`,
  and `ERR_CONNECTION_REFUSED`. The catalog, selected item, and editor were
  therefore not observable, so F02 was not evaluated as product `PASS` or
  `FAIL`.
- Reproduction: navigate to `http://localhost:3000`; observe the connection
  error before any application UI appears. No console, network, API, or source
  inspection was used, and no separate browser run ID was exposed.
- Evidence: one structured Astra journey with confidence `1.0`, the exact
  visible messages above, and the navigation diagnostic `net::ERR_CONNECTION_REFUSED`.
  No usable application screenshot could be collected because the UI never
  loaded; the structured evidence is preserved in this Markdown report.
- Limitation and direction: this is an environment availability blocker, not a
  confirmed product defect. Make the frontend reachable at the recorded URL,
  retain at least one registered flow, and rerun the unchanged F02 journey.
- Attempt totals: `PASS 0`, `FAIL 0`, `BLOCKED 1`; approval rate and executed
  coverage were not applicable before a reachable-environment rerun. No product
  finding was opened from this attempt.
- Residue: no run remains active; no fixture, registry entry, setting, or code
  was changed. The pre-existing F01 QA flows remain as previously documented.

**Execution `20260906-f02b` (2026-09-06, America/Bahia):**

- Environment: `http://localhost:3000`, base commit `d7b76ea`, backend on
  `:8000` and frontend on `:3000` started through their documented `make`
  targets, Chromium through Playwright MCP, 1280×720 capture viewport, and no
  authentication.
- Result: `FAIL` in 1m11s. Astra session
  `01a074ff-2fee-7d33-8052-0f530fca100c` opened Flows and observed `Untitled
  flow v0.1.0` and `QA-20260906-f01a-simple v0.1.0`. Clicking the QA item and
  waiting three seconds produced no selection, loading state, success, or error;
  the editor remained on `autodev/flow-feature-delivery@1.0.0` with its valid
  badge, so the selected flow's identity, version, and graph could not be
  confirmed.
- Reproduction: open the application → Flows → click
  `QA-20260906-f01a-simple v0.1.0` → wait three seconds → inspect the editor
  heading and feedback. The unchanged editor snapshot retained nodes `plan`,
  `code`, `apply-and-validate`, `quality-gate`, `human-review`, `evaluate`, and
  `escalate`, belonging to the previously displayed flow.
- Evidence: before/after browser snapshots, exact visible catalog and editor
  text, and one structured Astra journey with confidence `0.97`; no console,
  network, API, or source diagnostics were used. No persistent screenshot path
  or separate browser run ID was exposed.
- User impact and direction: a first-time user cannot open or maintain a
  registered flow. Make catalog selection load the chosen identity, version,
  and graph, and provide explicit open/selection feedback; then rerun unchanged
  F02. No correction was applied (`QA-002`).
- Secondary observation: with the Execution panel open, graph nodes were not
  visually discernible at 1280×720; this did not replace the primary failure.
- Batch totals (F02 rerun): `PASS 0`, `FAIL 1`, `BLOCKED 0`, `NOT_RUN 0`, planned
  `1`; approval rate `0%`, executed coverage `100%`. Highest-impact finding:
  `QA-002` (`S1`); there were no additional confirmed findings.
- Residue: backend and frontend remain active as requested; no flow, registry
  entry, setting, or code was changed by the run.

#### F03 — Editar propriedade de um nó (P1)

- **Instrução Astra:** `Change one node label and confirm that the canvas and inspector agree.`
- **Pré-condição:** flow temporário com agente no canvas.
- **Procedimento:** altere Label para `QA revised`; tire o foco; alterne nós.
- **PASS:** inspector e canvas concordam; demais propriedades permanecem.
- **Coletar:** inspector e canvas antes/depois.
- **Impacto:** detecta divergência entre estado editado e representação visual.

**Execution `20260906-f03a` (2026-09-06, America/Bahia):**

- Environment: `http://localhost:3001`, base commit `551eaf5`, existing backend
  reachable on `:8000`, frontend started with `make run-frontend`, Chromium
  through Playwright MCP, and no authentication.
- Result: `PASS` in 1m59s. Astra session
  `01a07505-f515-7743-8361-635100b464c5` selected the `plan` agent in
  `autodev/flow-feature-delivery@1.0.0`, changed only its blank Label field
  (placeholder `plan`) to `QA revised`, pressed Tab, selected `code`, and
  returned to the edited node. The canvas and inspector both retained
  `QA revised`.
- Preserved properties: node id `plan`, type `agent`, Ref
  `autodev/agent-planner@>=1.0 <2.0`, blank Model override and Timeout, and the
  single unguarded outgoing edge to `code`. The flow remained valid and the
  other canvas nodes and edge summary were unchanged.
- Evidence: structured before/after Astra observations and one completed
  journey with confidence `0.98`. The runner's temporary screenshots were
  removed with its temporary workspace, so no image path is cited. No console,
  network, API, source, or implementation diagnostics were used.
- Non-blocking observations: the landing page displayed `Could not load the
  chat workspace`, and the Flows library displayed
  `Request failed for v2/flows (404)`. Neither prevented this canvas-editing
  journey. Save/reload persistence was outside F03 and was not inferred.
- Execution note: one earlier runner invocation failed before browser or Astra
  session initialization because of a filesystem restriction; it is not a test
  attempt or product result.
- Batch totals: `PASS 1`, `FAIL 0`, `BLOCKED 0`, `NOT_RUN 0`, planned `1`;
  approval rate `100%` and executed coverage `100%`. No finding or correction
  was opened.
- Residue: the unsaved in-memory label `QA revised` remains in the frontend
  session; no flow was saved, no registry entry or setting was changed, and no
  product code or automated test was executed after the Astra run. The frontend
  remains active on `:3001`; the pre-existing backend remains active on `:8000`.

#### F04 — Renomear nó conectado (P1)

- **Instrução Astra:** `Rename one connected node and confirm that its connections remain valid.`
- **Pré-condição:** dois nós conectados.
- **Procedimento:** renomeie o primeiro ID para `qa-renamed`; examine aresta e Issues.
- **PASS:** novo ID efetivo, ligação preservada e nenhuma referência órfã.
- **Coletar:** ID, aresta e Issues antes/depois.
- **Impacto:** protege integridade referencial do grafo.

#### F05 — Recusar ID duplicado (P1)

- **Instrução Astra:** `Try to assign an existing node ID to another node and inspect the validation feedback.`
- **Pré-condição:** dois nós com IDs distintos.
- **Procedimento:** copie o primeiro ID no segundo; tire o foco; alterne seleção.
- **PASS:** duplicidade impedida com indicação compreensível e estado coerente.
- **Coletar:** valor digitado, feedback e valor efetivo ao reabrir.
- **Impacto:** evita grafo ambíguo. Rejeição silenciosa é achado de UX.

#### F06 — Excluir um nó conectado (P1)

- **Instrução Astra:** `Delete the middle node and inspect the remaining connections.`
- **Pré-condição:** grafo temporário A → B → C.
- **Procedimento:** selecione B; Delete node; confira canvas e Issues.
- **PASS:** B e suas arestas removidos; desconexões claras; nenhum nó alheio removido.
- **Coletar:** canvas e Issues antes/depois.
- **Impacto:** verifica mutação destrutiva local sem corrupção colateral.

#### F07 — Bloquear flow inválido (P1)

- **Instrução Astra:** `Remove a required agent reference and try to save the flow.`
- **Pré-condição:** flow temporário com nó agent.
- **Procedimento:** apague Ref; Save; abra Issues; restaure Ref válido.
- **PASS:** erro identificável, nenhum falso sucesso e recuperação após correção.
- **Coletar:** Ref vazio, erro, tentativa de Save e recuperação.
- **Impacto:** impede exportação/persistência enganosa de definição inválida.

#### F08 — Sincronizar visual e YAML (P1)

- **Instrução Astra:** `Change a node label in the inspector and verify the same change in the visible YAML editor.`
- **Pré-condição:** flow temporário válido.
- **Procedimento:** altere Label no inspector; confira `flow.yaml`; altere apenas
  o mesmo label no editor visível; volte ao canvas.
- **PASS:** sincronização nos dois sentidos sem perder nós ou arestas.
- **Coletar:** inspector, trecho do YAML e canvas final.
- **Impacto:** comprova uma única fonte de estado entre os dois modos de edição.

#### F09 — Recuperar YAML inválido (P1)

- **Instrução Astra:** `Introduce a YAML syntax error, inspect the error, then restore the original text.`
- **Pré-condição:** flow válido e texto original copiável pela UI.
- **Procedimento:** adicione `broken: [` ao final; examine Issues e Save; restaure.
- **PASS:** erro claro, nenhum falso estado válido e grafo original recuperado.
- **Coletar:** YAML inválido, Issues, tentativa de Save e estado recuperado.
- **Impacto:** valida edição textual segura e reversível.

#### F10 — Pré-visualizar aprovação humana (P1)

- **Instrução Astra:** `Preview a human approval node and inspect the approve and reject outcomes.`
- **Pré-condição:** exemplo com nó human e arestas de decisão.
- **Procedimento:** selecione `human-review`; acione as decisões da prévia.
- **PASS:** cada opção informa destino ou ausência de rota; não alega execução real.
- **Coletar:** prompt, opções, destinos e mensagens.
- **Impacto:** reduz ambiguidade de configuração. Não comprova governança runtime.

#### F11 — Proteger edição não salva (P1)

- **Instrução Astra:** `Edit a flow, navigate away, and return to check whether unsaved work is protected.`
- **Pré-condição:** flow temporário com mudança ainda não salva/exportada.
- **Procedimento:** Label `QA unsaved`; navegue para Sessions e volte.
- **PASS:** rascunho recuperado ou aviso antes de descartar.
- **Coletar:** alteração, aviso e estado ao retornar.
- **Impacto:** perda silenciosa é falha de aceitação/UX; não presumir autosave.

### Extensions

#### A01 — Criar agente mínimo (P0)

- **Instrução Astra:** `Create one minimal agent through the visible UI and verify that it remains listed after reload.`
- **Pré-condição:** modelo válido configurado e ID exclusivo.
- **Procedimento:** Extensions → Agents → Create agent; ID `qa-{RUN}-echo`, nome
  `QA Echo`, versão `1.0.0`, modelo configurado, ferramentas vazias e prompt
  `Return exactly QA_OK. Do not use tools.`; salve e recarregue.
- **PASS:** identidade, versão e prompt persistem e podem ser reabertos.
- **Coletar:** formulário, catálogo e detalhe após reload.
- **Impacto:** comprova autoria e durabilidade da extensão.

#### A02 — Editar agente existente (P1)

- **Instrução Astra:** `Edit one test agent and verify that the update persists without creating a duplicate.`
- **Pré-condição:** agente descartável de A01 ou equivalente.
- **Procedimento:** altere somente o nome para `QA Echo Revised`; salve e recarregue.
- **PASS:** nome persistido, mesmo ID e nenhuma duplicata.
- **Coletar:** ID, nomes antes/depois e contagem de entradas.
- **Impacto:** protege identidade e semântica de atualização.

#### A03 — Desativar e reativar agente (P1)

- **Instrução Astra:** `Disable one test agent, reload, then enable it again.`
- **Pré-condição:** agente QA ativo.
- **Procedimento:** desative; reload; confirme Inactive; reative; reload.
- **PASS:** estado e feedback persistem em ambas as transições.
- **Coletar:** switch, badge e estado após cada reload.
- **Impacto:** comprova governança básica sem alterar extensões compartilhadas.

#### A04 — Validar formulário obrigatório (P1)

- **Instrução Astra:** `Submit an incomplete agent form and inspect the validation feedback.`
- **Pré-condição:** formulário de novo agente acessível.
- **Procedimento:** deixe ID e prompt vazios; tente salvar; confira catálogo.
- **PASS:** campos identificados, nada criado e valores corrigíveis sem recomeçar.
- **Coletar:** formulário, erros e catálogo.
- **Impacto:** impede estado parcial e reduz retrabalho.

#### A05 — Inspecionar catálogo por tipo (P2)

- **Instrução Astra:** `Inspect Agents, Skills, Plugins, and MCP tabs and open one available item in each.`
- **Pré-condição:** catálogo acessível.
- **Procedimento:** visite cada aba; compare rótulo, tipo, contagem e cartões; abra
  um item disponível.
- **PASS:** tipos, descrição, versão, estado e vazios são compreensíveis.
- **Coletar:** captura por aba e detalhes abertos.
- **Impacto:** mede encontrabilidade; não exige editar tipos somente leitura.

### Chat e Routing

#### C01 — Executar pedido sem ferramentas (P0)

- **Instrução Astra:** `Send a small conversational request and check whether unnecessary execution is avoided.`
- **Pré-condição:** sessão nova e provider real.
- **Procedimento:** envie `Responda apenas QA_OK. Não leia nem modifique arquivos e não execute comandos.`
- **PASS:** resposta `QA_OK`, sem ação de arquivo/comando ou pipeline desnecessário.
- **Coletar:** mensagem, resposta, timeline e logs disponíveis.
- **Impacto:** protege custo, latência e princípio de menor ação. Stub bloqueia a
  avaliação LLM; ausência de logs limita comprovação.

#### C02 — Inspecionar arquivo sem modificar (P0)

- **Instrução Astra:** `Ask the agent to summarize one existing file without changing anything.`
- **Pré-condição:** `README.md` conhecido e visível em Files.
- **Procedimento:** abra o arquivo; peça resumo em três bullets sem mudanças/comandos.
- **PASS:** resumo sustentado e nenhuma alteração proposta/aplicada.
- **Coletar:** conteúdo relevante, resposta, patches e logs.
- **Impacto:** avalia grounding e respeito ao modo somente leitura; documente o
  limite se mutações ocultas não forem observáveis.

#### C03 — Criar um único arquivo (P0)

- **Instrução Astra:** `Create one small text file and verify its actual content in the Files screen.`
- **Pré-condição:** workspace QA, provider/execução e alvo ausente.
- **Procedimento:** peça somente `qa-{RUN}-hello.txt` com a linha `Hello AutoDev.`;
  cumpra gates visíveis; abra o arquivo.
- **PASS:** arquivo real, conteúdo exato e nenhuma mudança alheia.
- **Coletar:** pedido, aprovações, diff e Files.
- **Impacto:** distingue conclusão textual de artefato real.

#### C04 — Editar exatamente uma linha (P0)

- **Instrução Astra:** `Change one line in an existing test file and verify the diff and final file.`
- **Pré-condição:** arquivo de C03 com `Hello AutoDev.`.
- **Procedimento:** substitua por `Hello Astra.` e peça nenhuma outra alteração.
- **PASS:** uma substituição, arquivo final correto e nenhuma mudança extra.
- **Coletar:** diff e conteúdo final.
- **Impacto:** comprova precisão e escopo mínimo de patch.

#### C05 — Não acionar estruturação para edição (P0)

- **Instrução Astra:** `Request a tiny edit in an existing project and inspect which flow or agent is selected.`
- **Pré-condição:** projeto existente, flow de estruturação no catálogo e fixture.
- **Procedimento:** em nova sessão, reverta `Hello Astra.` para `Hello AutoDev.`;
  observe seleção e ações.
- **PASS:** execução simples ou flow adequado, nunca bootstrap incompatível; diff mínimo.
- **Coletar:** seleção/justificativa, passos e diff.
- **Impacto:** valida roteamento proporcional. Se seleção não for exposta,
  registre `BLOCKED` na comprovação e achado de observabilidade.

#### C06 — Escolher flow para projeto novo (P1)

- **Instrução Astra:** `Ask to structure a tiny new project and inspect whether the selected flow matches the task.`
- **Pré-condição:** workspace QA vazio, flow aplicável e provider real.
- **Procedimento:** peça plano mínimo para CLI Python que imprime hello, sem executar.
- **PASS:** flow adequado quando disponível, plano proporcional e nenhuma execução.
- **Coletar:** workspace vazio, seleção, plano e estado de execução.
- **Impacto:** testa adequação, justificativa e respeito à autorização.

#### C07 — Tratar pedido sem flow específico (P1)

- **Instrução Astra:** `Request a small task with no matching specialized flow and inspect the fallback.`
- **Pré-condição:** catálogo conferido sem flow específico para a tarefa.
- **Procedimento:** peça três nomes de função de soma, somente texto e sem projeto.
- **PASS:** resposta direta/agente adequado e nenhum flow alheio.
- **Coletar:** catálogo, pedido, resposta, seleção e ações.
- **Impacto:** evita uso compulsório de automação inadequada.

#### C08 — Impedir envio vazio e duplicado (P1)

- **Instrução Astra:** `Check empty submission and double-click submission for a tiny request.`
- **Pré-condição:** sessão ociosa e provider funcional.
- **Procedimento:** envie espaços; depois `Responda QA_ONCE` com clique duplo rápido.
- **PASS:** nenhum turno vazio e exatamente uma mensagem/turno válido.
- **Coletar:** composer, histórico, IDs e contagem.
- **Impacto:** evita consumo e efeitos duplicados.

#### C09 — Reabrir conversa persistida (P0)

- **Instrução Astra:** `Reload the page and reopen the same session to verify conversation persistence.`
- **Pré-condição:** sessão com duas mensagens e respostas concluídas.
- **Procedimento:** anote session ID; reload; Sessions → Open chat.
- **PASS:** mensagens e ordem preservadas, sem duplicação ou troca de sessão.
- **Coletar:** histórico e ID antes/depois.
- **Impacto:** comprova durabilidade e continuidade de trabalho.

#### C10 — Isolar duas sessões (P1)

- **Instrução Astra:** `Switch between two sessions and check that their messages and execution context do not mix.`
- **Pré-condição:** duas sessões QA independentes.
- **Procedimento:** envie `MARCADOR_A` na A e `MARCADOR_B` na B; alterne Chat,
  Plans e Execution.
- **PASS:** histórico, plano e run correspondem à sessão selecionada.
- **Coletar:** IDs, mensagens, planos e run ativo em cada contexto.
- **Impacto:** detecta mistura de contexto; decisões globais identificadas por run
  não constituem, isoladamente, vazamento.

### Governança, Execution, Patches e Files

#### E01 — Respeitar rejeição de passo (P0)

- **Instrução Astra:** `Reject one planned file change and verify that the rejected step is not executed.`
- **Pré-condição:** modo Approval, plano com criação de `qa-{RUN}-denied.txt` e alvo ausente.
- **Procedimento:** rejeite o passo; execute apenas aprovados; confira Files/log.
- **PASS:** passo não executado, arquivo ausente e status coerente.
- **Coletar:** rejeição, estado do passo, Files atualizado e log.
- **Impacto:** execução rejeitada é falha crítica de autorização; gate ausente bloqueia.

#### E02 — Aprovar uma ação e retomar (P0)

- **Instrução Astra:** `Approve one pending action once and resume the matching run.`
- **Pré-condição:** run pausado para criar arquivo QA.
- **Procedimento:** identifique ação/run; Approve once; Resume se necessário; confira
  arquivo e permissões.
- **PASS:** ação ocorre uma vez, run correto retoma e nenhuma regra persistente nasce.
- **Coletar:** decisão, session/run IDs, log, arquivo e permissões.
- **Impacto:** valida escopo de autorização; aprovação do plano não substitui gate da ação.

#### E03 — Negar ação pendente (P0)

- **Instrução Astra:** `Deny a pending file-write action and verify that it is not performed.`
- **Pré-condição:** run pausado para criar `qa-{RUN}-blocked.txt`.
- **Procedimento:** identifique ação/run; Deny; confira log e Files.
- **PASS:** nenhum efeito, motivo claro e nenhuma conclusão falsa de sucesso.
- **Coletar:** decisão, IDs, log e Files.
- **Impacto:** comprova enforcement negativo de autorização.

#### E04 — Conferir execução ao vivo (P1)

- **Instrução Astra:** `Observe a live run and check that progress, logs, and final status agree.`
- **Pré-condição:** tarefa QA pequena com duração observável.
- **Procedimento:** inicie criação de arquivo; acompanhe painel e Execution até terminal.
- **PASS:** progresso durante execução, logs ordenados/identificados e estado terminal
  coerente, sem sucesso antecipado ou spinner residual.
- **Coletar:** início, meio e fim com horário, IDs e mensagens; tempo até primeiro feedback.
- **Impacto:** valida confiança operacional; uma amostra não comprova SLO/p95.

#### E05 — Reconectar após reload (P1)

- **Instrução Astra:** `Reload during a run and check whether its progress and final result are recovered.`
- **Pré-condição:** run em andamento e IDs anotados.
- **Procedimento:** reload uma vez; reabra sessão; acompanhe até terminal; confira artefato.
- **PASS:** mesmo run, sem tarefa/arquivo duplicado nem progresso travado.
- **Coletar:** IDs antes/depois, timeline e artefato.
- **Impacto:** comprova continuidade. Se o run terminar antes do reload, use `NOT_RUN`
  e repita apenas com fixture adequada.

#### E06 — Exibir falha sem falso sucesso (P1)

- **Instrução Astra:** `Run a harmless command that fails and inspect the final status and error message.`
- **Pré-condição:** workspace QA e Python disponível.
- **Procedimento:** peça somente `python -c "raise SystemExit(7)"`, sem correção/repetição.
- **PASS:** falha e código 7 visíveis quando suportados, sem validação aprovada e com
  próximo passo compreensível.
- **Coletar:** pedido, comando efetivo, saída/código e estado final.
- **Impacto:** impede falso sucesso. Python ausente bloqueia o gatilho específico.

#### P01 — Revisar mudança antes de aplicar (P0)

- **Instrução Astra:** `Request a one-line patch and inspect it before allowing application.`
- **Pré-condição:** modo de revisão e arquivo com linha conhecida.
- **Procedimento:** peça proposta `Hello AutoDev` → `Hello Astra` e aguarde; abra
  Patches e Files antes de aprovar.
- **PASS:** diff identifica arquivo e linhas; original permanece intacto antes da autorização.
- **Coletar:** pedido, diff, estado de aprovação e original.
- **Impacto:** preserva revisão humana antes da mutação.

#### P02 — Conferir árvore e conteúdo (P0)

- **Instrução Astra:** `Navigate the file tree and inspect two known files.`
- **Pré-condição:** arquivo raiz e arquivo interno conhecidos.
- **Procedimento:** expanda pasta; abra ambos; alterne entre eles.
- **PASS:** caminho, título, conteúdo e seleção corretos, sem conteúdo anterior residual.
- **Coletar:** árvore, caminhos e trechos conhecidos.
- **Impacto:** valida identidade do artefato; não exige edição no viewer.

### Navegação, configuração, UX e resiliência

#### U01 — Abrir telas principais (P0)

- **Instrução Astra:** `Visit every primary screen through the sidebar and check for broken navigation.`
- **Pré-condição:** frontend acessível.
- **Procedimento:** visite Chat, Plans, Patches, Execution, Files, Flows, Sessions,
  Config e Extensions; use voltar/avançar uma vez.
- **PASS:** tela correta, item ativo, nenhum branco/erro não tratado e vazios explicados.
- **Coletar:** URL, captura e mensagens por tela.
- **Impacto:** smoke estrutural; não implica funcionamento completo do produto.

**Execution `20260906-u01a` (2026-09-06, America/Bahia):**

- Environment: `http://localhost:3000`, base commit `48ed752`, Chromium through
  Playwright MCP, viewport not exposed by the structured runner report, and no
  authentication prompt. Preflight initially found the frontend unavailable;
  the documented combined `make run` start did not expose port 3000, so the
  operator restarted the unchanged build with the documented separate
  `make run-backend` and `make run-frontend` targets. Frontend and backend then
  returned HTTP 200 and the backend health payload was `{"status":"ok"}`.
- Result: `BLOCKED` in 2m14s. Astra session
  `01a075ed-89bc-7d01-81d2-523dd8db72ad` reached all nine primary screens with
  the correct screen identity, URL, and active sidebar item. No screen was
  blank and no unhandled error screen appeared. Browser Back returned from
  Extensions to Config coherently, but browser Forward could not be verified
  with the permitted controls: `Alt+ArrowRight` had no effect, and an unsafe
  arbitrary-code attempt was rejected before execution. This is an evidence
  limitation, not a confirmed product defect.
- Observed navigation: Chat `/`; Plans `/plans`; Patches `/patches`; Execution
  `/execution`; Files `/files`; Flows `/flows`; Sessions `/sessions`; Config
  `/config`; and Extensions `/extensions`. Empty states or guidance were
  visible where applicable. Plans additionally rendered
  `Could not load the plan for that session.` while its session field appeared
  empty; this separate UX finding is recorded as `QA-003`.
- Evidence limitation: Astra captured each screen during the journey, but the
  runner exposed no persistent screenshot paths. The structured observations,
  exact visible text, URLs, interaction sequence, session, and result are
  preserved here. No browser-specific run id beyond the Astra session was
  exposed.
- Residue: no product data, settings, fixtures, or active runs were created or
  changed. Local frontend and backend processes remained active for delivery
  work and are stopped after documentation is complete.

#### U02 — Persistir opção não secreta (P1)

- **Instrução Astra:** `Change one non-secret setting, reload, and verify persistence.`
- **Pré-condição:** valor original do objetivo padrão registrado.
- **Procedimento:** altere para `QA-{RUN}-goal`; salve; reload; restaure.
- **PASS:** valor persistido, confirmação coerente e restauração bem-sucedida.
- **Coletar:** valor original, alterado e restaurado, sem credenciais.
- **Impacto:** valida persistência reversível; campo ausente bloqueia o caso.

#### U03 — Mostrar provider real ou stub (P0)

- **Instrução Astra:** `Check whether the UI accurately identifies the configured provider and any stub mode.`
- **Pré-condição:** configuração conhecida pelo operador.
- **Procedimento:** compare Config e indicador do Chat com provider/modelo informados.
- **PASS:** modo real, stub ou indisponível é inequívoco; stub não se passa por real.
- **Coletar:** indicadores e campos não secretos.
- **Impacto:** protege validade das evidências e confiança do usuário.

#### U04 — Usar painel em tela pequena (P1)

- **Instrução Astra:** `Check Chat and Flows at a narrow viewport and browser zoom of 200%.`
- **Pré-condição:** Chat com histórico/execução e flow temporário.
- **Procedimento:** use 1280×800, 768×900 e zoom 200%; abra/feche painel; alcance
  Send, Save e modais.
- **PASS:** controles acessíveis, texto legível, rolagem útil e sem sobreposição impeditiva.
- **Coletar:** viewport/zoom e capturas por tela.
- **Impacto:** detecta barreiras responsivas; não equivale a auditoria WCAG.

#### U05 — Operar formulário por teclado (P2)

- **Instrução Astra:** `Create an agent draft using keyboard navigation and close the dialog without saving.`
- **Pré-condição:** Extensions acessível.
- **Procedimento:** use Tab, Shift+Tab, Enter e Escape; percorra e feche Create agent.
- **PASS:** foco visível, ordem lógica, foco contido e retorno ao acionador.
- **Coletar:** sequência de teclas e capturas de foco.
- **Impacto:** avalia usabilidade básica por teclado sem salvar o rascunho.

#### U06 — Conferir tema e idioma (P2)

- **Instrução Astra:** `Switch theme and language and inspect the main user-facing labels.`
- **Pré-condição:** controles disponíveis.
- **Procedimento:** alterne claro/escuro e en/pt-BR; confira Chat, Sessions e Flows;
  reload; restaure preferências.
- **PASS:** temas legíveis, tradução coerente e retenção quando prometida.
- **Coletar:** capturas comparáveis e textos não traduzidos.
- **Impacto:** identifica inconsistência visual/textual; candidato no código não é
  falha reproduzida.

#### U07 — Preservar texto após indisponibilidade (P1)

- **Instrução Astra:** `Try to send a short message while the service is unavailable and inspect recovery.`
- **Pré-condição:** indisponibilidade restaurável preparada pelo operador.
- **Procedimento:** envie uma vez `QA recovery message`; capture erro/recuperação;
  após restauração, retente uma vez.
- **PASS:** erro claro, sem falso sucesso, texto recuperável e reenvio não duplicado.
- **Coletar:** texto antes/depois, erro e histórico final.
- **Impacto:** protege trabalho do usuário. Sem falha preparada, marque `BLOCKED`.

## 8. Registro de execução

Use uma linha por caso. Campos vazios nunca significam `PASS`. `Dinâmica`
registra sequência, feedback, espera, reload e comportamento intermediário;
`Correções/melhorias` referencia achados deduplicados ou `—` quando não houver.

| Caso | Estado | Resultado observado | Dinâmica | Evidências | Session/run | Duração | Achado/correção |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | FAIL | The valid graph saved only as `Untitled flow`; no visible control could set `QA-20260906-f01a-simple`, so named persistence after reload was not testable | Flows → New blank flow → Start → Planner → End → inspect visible controls → Save → unnamed catalog entry → stop | Structured Astra observations and exact UI text recorded in the F01 execution note and `QA-001`; screenshots blank/unusable | RUN `20260906-f01a`; primary session `01a074d5-ed65-7872-90a4-9ef02a570f92` | 2m12s | `QA-001`, open; correction direction only |
| F02 | FAIL | Catalog contained the QA flow, but clicking it left the editor on `autodev/flow-feature-delivery@1.0.0` without feedback | Flows → select `QA-20260906-f01a-simple v0.1.0` → unchanged editor → wait 3s → unchanged editor → stop | Before/after browser snapshots and exact UI text recorded in the F02 execution note | RUN `20260906-f02b`; session `01a074ff-2fee-7d33-8052-0f530fca100c` | 1m11s | `QA-002`, open; correction direction only |
| F03 | PASS | Canvas and inspector both retained `QA revised`; all other exposed node properties remained unchanged | Select `plan` → record properties → enter Label → Tab → select `code` → reselect edited node → confirm | Structured before/after Astra observations recorded in the F03 execution note; temporary screenshots unavailable after runner cleanup | RUN `20260906-f03a`; session `01a07505-f515-7743-8361-635100b464c5` | 1m59s | — |
| F04 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F05 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F06 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F07 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F08 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F09 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F10 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| F11 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| A01 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| A02 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| A03 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| A04 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| A05 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C01 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C02 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C03 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C04 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C05 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C06 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C07 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C08 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C09 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| C10 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| E01 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| E02 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| E03 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| E04 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| E05 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| E06 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| P01 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| P02 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| U01 | BLOCKED | All nine primary screens rendered with correct identity and active navigation; Back worked, but Forward could not be verified with permitted browser controls | Chat → Plans → Patches → Execution → Files → Flows → Sessions → Config → Extensions → Back to Config → `Alt+ArrowRight` had no effect → unsafe alternative rejected before execution → stop | Structured Astra observations, exact URLs/text, and U01 execution note; screenshots had no persistent paths | RUN `20260906-u01a`; session `01a075ed-89bc-7d01-81d2-523dd8db72ad` | 2m14s | `QA-003`, open; correction direction only; Forward limitation is not a product defect |
| U02 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| U03 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| U04 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| U05 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| U06 | NOT_RUN | Ainda não executado | — | — | — | — | — |
| U07 | NOT_RUN | Ainda não executado | — | — | — | — | — |

Nome de evidência recomendado:
`{RUN}_{CASO}_{01-before|02-action|03-result}.png`. Use links reais; nunca
invente caminhos. Registre horário e timezone e preserve o texto exato de erros.

## 9. Achados e mudanças inferidas

Deduplicate por sintoma observável, não por causa presumida. Uma tarefa pode
referenciar vários casos, mas problemas diferentes não devem ser agrupados
apenas porque apareceram no mesmo run.

```text
ID: QA-001
Título: <ação concreta + comportamento afetado>
Tipo: bug funcional | lacuna de funcionalidade | UX | observabilidade | ambiente
Severidade: S0 | S1 | S2 | S3
Casos relacionados:
Build/URL:
Pré-condições:
Reprodução mínima:
Esperado:
Observado:
Frequência: <ocorrências/tentativas>
Evidências:
Impacto no usuário:
Hipótese de causa: <opcional e explicitamente não confirmada>
Correção/melhoria proposta:
Critérios de aceite:
Dependências:
Como retestar:
```

Uma capacidade aparentemente ausente na inspeção de implementação é apenas uma
candidata até ser executada no build instalado. Por exemplo, persistir e reabrir
flows deve ser confirmado por `F01`/`F02`; antes disso, não registrar como bug
reproduzido.

### QA-001 — Name and persist a new flow through visible controls

- **Type/severity:** functional bug, `S1`.
- **Related case:** `F01`.
- **Build/URL:** base commit `5a011fe`; `http://localhost:3000`.
- **Preconditions:** reachable UI and API; no test flow open; disposable name
  `QA-20260906-f01a-simple`.
- **Minimal reproduction:** Flows → New blank flow → Start → Planner → End →
  Save.
- **Expected:** a visible control sets the requested name and the named catalog
  entry remains after reload.
- **Observed initially:** no naming control was visible; Save reported
  `autodev/flow-untitled@0.1.0 registered.` and the catalog displayed
  `Untitled flow`. Reproduced once in one attempt.
- **User impact:** the central flow-authoring journey could not create a
  distinguishable named artifact.
- **Correction direction:** add a visible Flow name field, derive or request a
  registry-safe identity without hidden YAML editing, and cover named
  save/reload behavior in the existing flow-builder E2E test.
- **Acceptance/retest:** enter the QA name without YAML, save a valid graph,
  reload, and observe the same named version in the catalog. The finding remains
  open until that implementation is delivered and F01 passes on its committed
  build.
- **Evidence:** structured Astra journey and exact visible messages recorded in
  the F01 execution note; screenshots were blank and excluded as proof.

### QA-002 — Open a registered flow from the catalog

- **Type/severity:** functional bug, `S1`.
- **Related case:** `F02`.
- **Build/URL:** base commit `d7b76ea`; `http://localhost:3000`.
- **Preconditions:** reachable UI and API; catalog containing
  `QA-20260906-f01a-simple v0.1.0`.
- **Minimal reproduction:** Flows → click the QA catalog item → wait three
  seconds → inspect the editor heading and feedback.
- **Expected:** the editor displays the selected flow's name, version, and
  corresponding graph.
- **Observed:** no selection or loading feedback appeared, and the editor stayed
  on `autodev/flow-feature-delivery@1.0.0`. Reproduced once in one reachable-UI
  attempt.
- **User impact:** registered flows cannot be reopened for inspection or
  maintenance through the visible catalog journey.
- **Correction direction:** make the catalog item or an explicit Open action
  load the selected registered version and show selection, loading, success,
  and failure states.
- **Acceptance/retest:** select the QA item and confirm its exact identity,
  version `0.1.0`, and nodes in the editor; rerun F02 on the corrected committed
  build. No correction was applied in this documentation-only delivery.
- **Evidence:** structured Astra journey, before/after browser snapshots, and
  exact visible text recorded in the F02 execution note; no persistent
  screenshot path was exposed.

### QA-003 — Explain automatic plan loading for the active session

- **Type/severity:** UX, `S2`.
- **Related case:** `U01`.
- **Build/URL:** base commit `48ed752`; `http://localhost:3000/plans`.
- **Preconditions:** reachable UI and API; an active Chat session without a
  loadable plan; the Plans session field appears empty.
- **Minimal reproduction:** open Chat → click Plans in the visible sidebar →
  inspect the session field, alert, and empty-state guidance.
- **Expected:** show neutral plan-selection guidance, or identify the session
  whose automatic plan lookup failed and explain how to recover.
- **Observed:** Plans displayed `Could not load the plan for that session.`
  immediately while the visible session field was empty. Reproduced once in
  the U01 journey.
- **User impact:** a first-time user sees an unexplained failed lookup before
  entering a session id and cannot tell which session was requested.
- **Correction direction:** expose the automatically selected session in the
  field or alert, distinguish a missing plan from service errors, and provide a
  recovery action such as choosing another session or returning to Chat.
- **Acceptance/retest:** with an active session that has no plan, open Plans and
  verify that the selected session and recovery path are explicit without a
  misleading generic error. No product or test-framework changes are included
  in this documentation-only delivery.
- **Evidence:** rendered alert, visible empty session field, URL, and structured
  Astra observations preserved in the U01 execution note; no persistent
  screenshot path was exposed.

## 10. Fechamento do lote e atualização documental

Ao concluir um lote:

1. registre totais de `PASS`, `FAIL`, `BLOCKED` e `NOT_RUN` e os três achados de
   maior impacto;
2. calcule `taxa de aprovação = PASS / (PASS + FAIL)` e
   `cobertura executada = (PASS + FAIL) / casos planejados no lote`, sempre
   exibindo bloqueados e total planejado;
3. liste runs ativos, fixtures, resíduos e configurações não restauradas;
4. atualize este registro e todos os Markdown afetados pelo comportamento real;
5. crie uma branch curta de documentação/correção a partir de `main`, faça commit,
   abra PR, conclua os gates proporcionais ao escopo, aceite o PR em `main`,
   sincronize local/remoto e remova branches já integradas.

Não calcule p95 a partir de uma execução e não use sucesso visual para afirmar
correção interna. Após preservar o resultado inicial, um defeito de implementação
confirmado pode seguir o ciclo limitado de correção e repetição do mesmo cenário
definido pela skill `astra-user-test`, sempre registrando antes/depois. Lacunas
aspiracionais viram backlog com critérios de aceite e só são implementadas quando
o pedido incluir esse escopo.

### Closure — requested F01 batch

- Final totals for the requested one-case batch: 0 `PASS`, 1 `FAIL`, 0
  `BLOCKED`, 0 `NOT_RUN`; approval rate 0% and executed coverage 100%.
- Whole-catalog totals: 1 `FAIL` and 40 `NOT_RUN`.
- `QA-001` remains open. This delivery contains documentation and correction
  direction only; no product code or automated test changes are included.
- No active runs or configuration changes remain. The two disposable local
  flow fixtures listed in the F01 execution note remain as test residue.

### Closure — requested F03 batch

- Final totals for the requested one-case batch: 1 `PASS`, 0 `FAIL`, 0
  `BLOCKED`, 0 `NOT_RUN`; approval rate 100% and executed coverage 100%.
- Whole-catalog totals after this run: 1 `PASS`, 2 `FAIL`, and 38 `NOT_RUN`.
- No defect was inferred from F03 and no correction was applied. The two
  non-blocking error messages observed outside the tested interaction are
  recorded above without expanding this case's scope.
- This delivery changes documentation only. The unsaved in-memory label and
  active services are the only new execution residues described for this run.

### Closure — requested U01 batch

- Final totals for the requested one-case batch: 0 `PASS`, 0 `FAIL`, 1
  `BLOCKED`, 0 `NOT_RUN`; approval rate is not applicable because no case
  reached `PASS` or `FAIL`, and executed coverage is 0% under the catalog
  formula, with 1 blocked case out of 1 planned.
- Whole-catalog totals after this run: 1 `PASS`, 2 `FAIL`, 1 `BLOCKED`, and 37
  `NOT_RUN`.
- `QA-003` remains open as correction direction only. Forward navigation remains
  unverified because the safe browser controls exposed to Astra could not
  perform it; this limitation is not classified as a product defect.
- This delivery changes Markdown documentation only. No product code,
  configuration, fixtures, or automated tests were changed; no automated test
  result is cited, and delivery validation was limited to documentation diff
  checks.
