# lab019-site

Página inicial institucional da **Lab019**, publicada como site estático.

## O que é este repositório

Site estático puro: nenhum build, nenhum framework, nenhuma dependência de runtime.
A página é composta por arquivos versionados na raiz do repositório:

| Arquivo        | Papel                                                              |
| -------------- | ------------------------------------------------------------------ |
| `index.html`   | Página inicial (HTML5, autocontida, sem recurso externo)            |
| `styles.css`   | Folha de estilo local (tipografia de sistema, layout responsivo)    |
| `vercel.json`  | Configuração explícita de deploy estático                           |
| `tests/`       | Testes de aceitação (biblioteca padrão do Python, sem dependências) |

Conteúdo da página (pt-BR): engenharia de software, automação de processos e
agentes de IA — sem métricas, clientes, endereços ou certificações inventadas.

## Rodar localmente

Servir a raiz do repositório com o servidor HTTP da biblioteca padrão:

```bash
python3 -m http.server 8000 --directory .
```

Depois abra <http://127.0.0.1:8000/>. Como `index.html` está na raiz, a rota `/`
já devolve a página (sem listagem de diretório).

## Rodar os testes

A partir da raiz do repositório:

```bash
python3 -m unittest discover -s tests -v
```

Os testes cobrem 7 critérios: existência e estrutura do HTML, viewport, único
`<h1>`, âncoras internas resolvendo para ids reais, parágrafo-lead e contato
(`mailto:contato@lab019.ai`), ausência de recursos externos e `vercel.json`
válido — além de servir a raiz via `python3 -m http.server` e conferir a
resposta de `GET /`.

## Publicação

A publicação é feita pelo **Lume-infra** (Vercel). Este repositório não tem
pipeline de build: o deploy é o diretório raiz como site estático, com
`vercel.json` descrevendo a configuração. Não há passo de CI/CD aqui, e nenhum
artefato gerado deve ser commitado (ver `.gitignore`).
