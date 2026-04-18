# Import de Contatos v2 — Design Spec

**Data:** 2026-04-18
**Status:** Aprovado
**Autor:** Felippe + Claude

## Problema

O import atual (`/import` → CSV → preview → confirmar) pula duplicatas silenciosamente. O usuário não tem controle sobre o que acontece com contatos que já existem. Para multi-tenant (Fase 3), cada tenant precisa decidir explicitamente o que entra na sua base.

## Decisões de Design

- **Abordagem:** Preview agrupado com atalhos rápidos + revisão individual opcional
- **Formatos:** CSV (.csv) e Excel (.xlsx)
- **Duplicatas:** 4 ações — Pular, Importar novo, Mesclar, Substituir
- **Princípio UX:** Guiar o usuário com opções estruturadas (Princípio #6)

## Formatos Suportados

### CSV (.csv)
Lógica existente em `import_csv.py`. Mantém compatibilidade com BOM, UTF-8, latin-1 fallback.

### Excel (.xlsx)
Nova dependência: `openpyxl` (read-only mode). Primeira linha = cabeçalho. Mesmas colunas válidas do CSV:

```
display_name (obrigatório), company, role, cadence_days, 
relationship_type, tags (separadas por |), how_we_met
```

Detecção automática pelo `file_name` do upload (.csv vs .xlsx/.xls).

## Fluxo Completo

### 1. Comando /import

```
Usuário: /import
Alfred: envia template CSV + instruções
        "📥 Como importar contatos em massa:
         1. Abra o template no Excel ou Google Sheets
         2. Preencha seus contatos
         3. Salve como CSV ou envie o Excel direto (.xlsx)
         4. Envie o arquivo aqui
         Máximo de 100 contatos por importação."
```

Template CSV continua o mesmo. Não gerar template Excel (CSV abre em qualquer editor).

### 2. Upload do arquivo

```
Usuário: envia arquivo.csv ou arquivo.xlsx
Alfred:
  → Detecta formato pelo file_name
  → Parse (CSV ou XLSX)
  → Validação de colunas e tipos
  → Se erros: mostra erros, para
  → Duplicate check: find_similar_contacts() para cada row
  → Separa em clean_rows e duplicates
  → Mostra preview agrupado
```

### 3. Preview Agrupado

```
📋 Arquivo válido — 15 contatos encontrados:

✅ 12 contatos novos:
• Ana Costa — Empresa Z · Diretora · 15d
• Pedro Lima — Startup W · CTO · 30d
• ... (mostra até 10, depois "e mais N")

⚠️ 3 já existem na sua base:
• João Silva (CSV: Empresa X · CEO) → já existe (BTG Pactual · Analista)
• Maria Santos (CSV: Google · PM) → já existe (Google · Engenheira)
• Carlos Ramos (CSV: sem empresa) → já existe (Carlos R. · Nubank)

O que fazer com os duplicatas?
[✅ Importar novos + Pular duplicatas]
[📥 Importar todos como novos]
[🔍 Revisar duplicatas um a um]
```

Se não houver duplicatas, mostra o preview simples atual com [Confirmar] / [Cancelar].

### 4. Cenários de Decisão

#### Cenário A — "Importar novos + Pular duplicatas" (atalho rápido)
- Importa os `clean_rows`
- Ignora os `duplicates`
- Vai direto para o relatório final

#### Cenário B — "Importar todos como novos"
- Importa `clean_rows` + todos os `duplicates` como contatos novos
- Vai para o relatório final

#### Cenário C — "Revisar duplicatas um a um"
- Para cada duplicata, mostra comparação lado a lado:

```
📊 Duplicata 1/3 — João Silva

📄 Dados do arquivo:
  Empresa: Empresa X
  Cargo: CEO
  Cadência: 15 dias
  Tags: cliente, vip

👤 Contato existente:
  Empresa: BTG Pactual
  Cargo: Analista
  Cadência: 30 dias
  Tags: profissional

[Pular] [Importar novo] [Mesclar] [Substituir]
```

Após decidir o último duplicata, executa todas as ações e vai para o relatório.

### 5. Semântica das 4 Ações

| Ação | Comportamento | Campos existentes | Campos do CSV |
|------|--------------|-------------------|---------------|
| **Pular** | Ignora a linha do CSV | Mantém | Descartados |
| **Importar novo** | `create_contact_confirmed()` com dados do CSV | Mantém (contato separado) | Novo contato |
| **Mesclar** | `update_contact()` no existente | Preservados se preenchidos | Usados apenas para preencher vazios |
| **Substituir** | `update_contact()` no existente | Sobrescritos | Usados todos |

### 6. Relatório Final

```
✅ Importação concluída!

• 12 contatos criados
• 2 duplicatas pulados
• 1 mesclado (João Silva — campos atualizados: empresa, cargo)
• 0 substituídos
```

## Arquitetura

### Arquivos a modificar

| Arquivo | Mudança |
|---------|---------|
| `alfred/services/import_csv.py` | Renomear para `import_contacts.py`. Adicionar `parse_xlsx()`, `check_duplicates()`, `merge_contact()`, `replace_contact()`. Atualizar `build_preview()`. |
| `alfred/bot/handlers.py` | `import_document_handler()` aceita .xlsx. Novos callbacks para decisões de duplicata. Estado em `context.user_data`. |
| `alfred/bot/keyboards.py` | `import_preview_keyboard()` (3 botões). `duplicate_review_keyboard(index, total)` (4 botões). |
| `pyproject.toml` | Adicionar `openpyxl` como dependência. |
| Imports internos | Atualizar todos os `from alfred.services.import_csv` para `import_contacts`. |

### Estado durante revisão

```python
context.user_data[f"import:{user_id}"] = {
    "clean_rows": [...],
    "duplicates": [
        {
            "csv_row": {"display_name": "João", "company": "X", ...},
            "existing": {"id": "abc-123", "display_name": "João", "company": "BTG", ...},
        },
    ],
    "decisions": {},                # {0: "skip", 1: "merge", ...}
    "current_review_index": 0,
}
```

Limpo após importação ou cancelamento. Chave inclui `user_id` para isolamento multi-tenant.

### Callback Data Convention

```
import:clean_and_skip:{user_id}     → Cenário A
import:import_all:{user_id}         → Cenário B
import:review:{user_id}             → Cenário C (inicia revisão)
import:dup_skip:{user_id}:{index}   → Pular duplicata N
import:dup_new:{user_id}:{index}    → Importar como novo
import:dup_merge:{user_id}:{index}  → Mesclar
import:dup_replace:{user_id}:{index}→ Substituir
import:cancel                       → Cancelar tudo
```

### Funções novas em import_contacts.py

```python
def parse_xlsx(xlsx_bytes: bytes) -> tuple[list[dict], list[str]]
    """Parse Excel, retorna (rows, errors). Mesma validação do CSV."""

async def check_duplicates(user_id: str, rows: list[dict]) -> tuple[list[dict], list[dict]]
    """Retorna (clean_rows, duplicates). Cada duplicata inclui csv_row + existing match."""

def build_grouped_preview(clean: list[dict], duplicates: list[dict]) -> str
    """Preview com seções ✅ novos e ⚠️ duplicatas."""

def build_duplicate_comparison(dup: dict, index: int, total: int) -> str
    """Comparação lado a lado para revisão individual."""

async def merge_contact(user_id: str, existing_id: str, csv_row: dict) -> str
    """Atualiza campos vazios do existente com dados do CSV."""

async def replace_contact(user_id: str, existing_id: str, csv_row: dict) -> str
    """Sobrescreve campos do existente com dados do CSV."""

async def execute_import(user_id: str, clean_rows: list[dict], duplicates: list[dict], decisions: dict) -> dict
    """Executa import completo: cria novos + aplica decisões dos duplicatas."""
```

## Verificação

1. Upload CSV com 5 contatos novos → preview sem duplicatas → confirmar → 5 criados
2. Upload XLSX com 3 novos + 2 duplicatas → preview agrupado → "Importar novos + Pular" → 3 criados, 2 pulados
3. Upload com duplicatas → "Revisar um a um" → testar cada ação (pular/importar/mesclar/substituir)
4. Upload com CSV inválido (coluna errada) → erro claro
5. Upload com .xlsx e encoding especial (acentos) → parse correto
6. Cancelamento no meio da revisão → estado limpo, nada importado
7. Arquivo com 101 linhas → erro de limite
