# AutoDev Architect

Guia rápido para executar o projeto em modo de desenvolvimento.

## Pré-requisitos

- Python 3.11+
- Node.js 18+
- npm (ou outro gerenciador compatível, como `pnpm` ou `yarn`)

## Configurando e executando o backend (FastAPI)

1. Crie e ative um ambiente virtual (opcional, mas recomendado):

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\\Scripts\\activate   # Windows
   ```

2. Instale as dependências (incluindo LangChain, LangGraph e o cliente selecionado para o LLM):

   ```bash
   pip install -r backend/requirements.txt
   ```

3. Inicie a API:

   ```bash
   uvicorn backend.api.main:app --reload
   ```

   A API ficará disponível em `http://localhost:8000`. O endpoint `/docs` oferece a documentação interativa.

### Configurando o LLM

O backend utiliza LangChain e LangGraph para coordenar os agentes. Por padrão, ele executa uma implementação "stub" totalmente determinística — útil para desenvolvimento local sem custos adicionais. Para utilizar um LLM real configure as seguintes variáveis de ambiente antes de iniciar o servidor:

- `LLM_PROVIDER`: defina como `openai` para usar o `ChatOpenAI` via `langchain-openai` (valor padrão: `stub`).
- `OPENAI_API_KEY`: chave de API obrigatória para o provedor OpenAI.
- `OPENAI_MODEL`: modelo desejado (por exemplo, `gpt-4o-mini`).
- `OPENAI_TEMPERATURE`: temperatura de amostragem (opcional, padrão `0.2`).
- `OPENAI_BASE_URL`: URL base alternativa, caso utilize um endpoint compatível.

Exemplo de execução com o provedor oficial da OpenAI:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o-mini"

uvicorn backend.api.main:app --reload
```

Com as variáveis configuradas, os agentes passarão a invocar o modelo via LangChain; caso alguma credencial esteja ausente, o backend retorna automaticamente às respostas estáticas pré-configuradas.

## Configurando e executando o frontend (Next.js)

1. Em outro terminal, instale as dependências:

   ```bash
   cd frontend
   npm install
   ```

2. Inicie o servidor de desenvolvimento:

   ```bash
   npm run dev
   ```

3. A interface ficará acessível em `http://localhost:3000`.

> **Dica:** Caso deseje apontar a interface para uma API remota, defina a variável de ambiente `NEXT_PUBLIC_API_URL` antes de iniciar o frontend.

## Testes rápidos

Para validar o fluxo principal do orquestrador execute:

```bash
pytest tests/backend/test_orchestrator.py
```
