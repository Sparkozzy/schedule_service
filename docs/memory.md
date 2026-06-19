# Registro de Memória (Self-Reflection)

Este documento contém as lições aprendidas durante o desenvolvimento e experimentação com MLFlow e Python neste projeto. O agente deve consultar este log antes de cada nova tarefa.

---

### [2026-05-08] — SyntaxError: Unicode Error em caminhos Windows
- **Contexto:** Carregamento de arquivo CSV utilizando caminhos absolutos no Windows.
- **Erro:** `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes...`
- **Causa raiz:** O Python interpreta a barra invertida (`\`) como um caractere de escape. O prefixo `\U` em `\Users` foi interpretado como o início de um código Unicode de 32 bits inválido.
- **Solução:** Usar barras normais (`/`), caminhos relativos ou raw strings (`r"..."`).
- **Lição:** **Nunca** use barras invertidas simples em caminhos de arquivos no Windows. Prefira sempre barras normais ou o uso de `os.path.join`.

---

### [2026-05-08] — FileNotFoundError por CWD incorreto
- **Contexto:** Execução de scripts localizados em subpastas (ex: `MLFlow_scripts/first.py`).
- **Erro:** `FileNotFoundError: [Errno 2] No such file or directory: 'data/ligacoes.csv'`
- **Causa raiz:** O script assumia que a pasta `data` estava no diretório de execução atual (CWD), mas o usuário estava rodando o script de dentro da subpasta.
- **Solução:** Implementar caminhos dinâmicos baseados no diretório do arquivo.
- **Lição:** Use `os.path.abspath(__file__)` para calcular a localização do script e navegar até os dados de forma relativa, garantindo portabilidade.

---

### [2026-05-08] — UnicodeEncodeError (Emoji) no Terminal Windows
- **Contexto:** Finalização de uma Run do MLFlow no console padrão do Windows.
- **Erro:** `UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f3c3'...`
- **Causa raiz:** O MLflow tenta imprimir emojis (🏃, 🧪) no sucesso da Run. O console Windows (CP1252) não suporta esses caracteres, quebrando o script no final do processo.
- **Solução:** Forçar a saída padrão para UTF-8 no início do script.
- **Lição:** Scripts que utilizam bibliotecas "modernas" (como MLflow) no Windows devem conter `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` no topo.

---

### [2026-05-08] — Artefatos do MLFlow "desaparecidos" (Local vs Remoto)
- **Contexto:** Verificação de modelos e arquivos no servidor remoto MLflow.
- **Erro:** "No Artifacts Recorded" na interface web, apesar de o script reportar sucesso.
- **Causa raiz:** O servidor não estava com a flag `--serve-artifacts` ativa. O servidor informava ao cliente um caminho local (`/data/artifacts/`), e o cliente Windows salvava os arquivos localmente em `C:\data\artifacts\` em vez de fazer o upload.
- **Solução:** Ativar `--serve-artifacts` no servidor (Easypanel) e criar um **novo experimento** (o experimento antigo mantém a rota local errada no banco de dados).
- **Lição:** Verifique sempre o `artifact_location` do experimento. Se for um path local, os artefatos não subirão para a nuvem sem configuração de proxy no servidor.

---

### [2026-05-08] — DtypeWarning e Performance em CSVs grandes
- **Contexto:** Leitura do arquivo `ligacoes.csv` (200MB+).
- **Erro:** `DtypeWarning: Columns (...) have mixed types. Specify dtype option...`
- **Causa raiz:** O Pandas tenta inferir os tipos por blocos; em arquivos grandes, colunas com dados inconsistentes causam lentidão e avisos.
- **Solução:** Adicionar `low_memory=False` ao `pd.read_csv()`.
- **Lição:** Para arquivos de dados volumosos no padrão EDW, o uso de `low_memory=False` é mandatório para silenciar avisos e evitar bugs de tipo na inferência de ML.

---

### [2026-05-08] — Ordem do MLflow Autolog
- **Contexto:** Registro automático de parâmetros e métricas.
- **Erro:** Artefatos e métricas não apareciam na Run, mesmo com `autolog()` ativo.
- **Causa raiz:** O `mlflow.sklearn.autolog()` foi chamado após o treinamento (`fit`). Ele precisa ser chamado **antes** para interceptar a execução.
- **Solução:** Mover as configurações de MLflow e o `autolog()` para a primeira célula de configuração do script.

---

### [2026-05-08] — Falha no MCP por dependência de 'uv' ausente
- **Contexto:** Tentativa de acesso às ferramentas do MCP do MLflow.
- **Erro:** Ferramentas não apareciam na lista de ferramentas disponíveis.
- **Causa raiz:** O `mcp_config.json` utilizava `uv run`, mas o executável `uv` não estava instalado no sistema.
- **Solução:** Alterar o comando para `python -m mlflow mcp run` e garantir a instalação de `mlflow[mcp]`.
- **Lição:** Verifique sempre se os executáveis definidos no `mcp_config.json` estão disponíveis no PATH. Prefira `python -m` para ferramentas Python se o ambiente não possuir `uv`.

---

### [2026-05-08] — Perda de Precisão e Notação Científica em Identificadores
- **Contexto:** Leitura de IDs e números de telefone (`to_number`, `call_id`) via `pd.read_csv`.
- **Erro:** Números como `5519...` convertidos para `5.519...e+12`, perdendo a capacidade de aplicar regex ou slices de string.
- **Causa raiz:** O Pandas infere colunas numéricas longas como float por padrão. Ao salvar e re-ler o CSV sem especificar o `dtype`, a conversão ocorre automaticamente.
- **Solução:** Sempre especificar `dtype={'coluna': str}` no `read_csv` para qualquer campo que funcione como identificador ou que exija extração de sub-strings.
- **Lição:** Dados de telefonia **não são números**, são strings numéricas. Trate-os como tal desde a ingestão.

---

### [2026-05-08] — ValueError em Gráficos (Zero-size array)
- **Contexto:** Geração de Heatmaps com Seaborn após filtros de feature engineering.
- **Erro:** `ValueError: zero-size array to reduction operation fmin`.
- **Causa raiz:** Uma falha na lógica de extração do DDD (índices incorretos devido ao prefixo `+`) resultou em uma coluna de DDDs vazia após o filtro de validação, fazendo com que a pivot table do gráfico ficasse vazia.
- **Solução:** Implementar funções de extração mais robustas que tratem múltiplos prefixos (`+55`, `55`, ou nenhum) e validar o shape do DataFrame antes de plotar.
- **Lição:** Filtros de "limpeza básica" podem ser silenciosamente fatais. Sempre verifique o `df.shape` ou `value_counts()` após uma operação de limpeza crítica.

---

### [2026-05-08] — Erro de Permissão em Caminhos de Artefatos
- **Contexto:** Criação de relatório Markdown utilizando a ferramenta `write_to_file` com `IsArtifact: true`.
- **Erro:** `... is not a valid artifact path; artifacts must be in [AppDir]`.
- **Causa raiz:** Tentativa de salvar o artefato dentro da pasta do projeto (`docs/`) em vez do diretório de artefatos gerenciado pelo sistema.
- **Solução:** Utilizar o caminho absoluto fornecido pelo erro ou apenas o nome do arquivo, garantindo que a flag `IsArtifact` esteja correta.
- **Lição:** Documentos gerados para o usuário (relatórios, walkthroughs) devem seguir o protocolo de diretórios do sistema de IA, enquanto scripts e dados de treino ficam no workspace do projeto.

---

### [2026-05-11] — Erro de Integridade: Amostragem Indevida na Ingestão
- **Contexto:** Criação do script `ingestao_dados.py` para espelhamento local do Supabase.
- **Erro:** Uso de `.limit(100000)` truncando a extração de dados.
- **Causa raiz:** Suposição equivocada de que uma amostra seria suficiente para EDA, ignorando que o objetivo da ingestão é o espelhamento fiel para permitir tratamento completo no arquivo de análise. Isso causou a perda de agentes com menor volume (ex: Gatekeeper).
- **Solução:** Implementar paginação para garantir a extração de 100% dos registros da tabela.
- **Lição:** A camada de ingestão deve ser um espelho (mirror) dos dados brutos. Filtros, amostragens e limpezas devem ser responsabilidade exclusiva da camada de análise/EDA. Nunca limite a extração inicial a menos que haja restrição técnica intransponível de hardware.
---

### [2026-05-11] — AttributeError: 'OutStream' object has no attribute 'buffer'
- **Contexto:** Aplicação do fix de UTF-8 para emojis do MLflow em ambiente interativo (VS Code/Jupyter).
- **Erro:** `AttributeError: 'OutStream' object has no attribute 'buffer'`
- **Causa raiz:** Em kernels interativos, o `sys.stdout` não é um arquivo padrão do SO, mas um objeto `OutStream` que não possui o atributo `.buffer`.
- **Solução:** Envolver a redefinição em um check `if hasattr(sys.stdout, 'buffer'):`.
- **Lição:** Sempre valide a existência do buffer antes de tentar re-encodar a saída padrão, garantindo que o script funcione tanto em terminal puro quanto em notebooks.
