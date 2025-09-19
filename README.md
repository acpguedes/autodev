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

2. Instale as dependências:

   ```bash
   pip install -r backend/requirements.txt
   ```

3. Inicie a API:

   ```bash
   uvicorn backend.api.main:app --reload
   ```

   A API ficará disponível em `http://localhost:8000`. O endpoint `/docs` oferece a documentação interativa.

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
