# Registro rápido pelo iPhone

Registre despesas pelo app **Atalhos** do iOS, sem abrir o MONETTA.

## Antes de começar

O iPhone precisa alcançar o servidor por um endereço com HTTPS. Com o app rodando só no
computador (`localhost`), o atalho não funciona. Veja **Publicar em produção** no [README](../README.md).

## 1. Criar o token

1. No MONETTA, abra **Configurações → Integrações**.
2. Dê um nome, como `iPhone`, e clique em **Criar token**.
3. Copie o valor. Ele aparece uma única vez.

O token só registra despesas e consulta as opções do atalho. Ele não abre saldos nem outros
dados. Se perder o aparelho, clique em **Revogar**.

## 2. Montar o atalho

No app Atalhos, crie um atalho com estas ações, nesta ordem:

| # | Ação | Configuração |
|---|---|---|
| 1 | Pedir Entrada | Tipo **Número**, pergunta "Valor" |
| 2 | Pedir Entrada | Tipo **Texto**, pergunta "Descrição" |
| 3 | Escolher do Menu | "Categoria", com as mesmas categorias do MONETTA |
| 4 | Obter Conteúdo do URL | Veja abaixo |
| 5 | Obter Valor do Dicionário | Chave `message` |
| 6 | Mostrar Notificação | Exibe o valor obtido |

Na ação 3, cada opção do menu precisa de uma ação **Texto** com o nome da categoria. Depois do
menu, use **Se** ou **Definir Variável** para guardar a escolha em `Categoria`.

### Ação "Obter Conteúdo do URL"

- **URL:** `https://SEU-DOMINIO/api/integrations/expenses`
- **Método:** `POST`
- **Cabeçalhos:** `Authorization` com o valor `Bearer SEU_TOKEN`
- **Corpo da Solicitação:** `JSON`

| Campo | Tipo | Valor |
|---|---|---|
| `amount` | Texto | variável da ação 1 |
| `description` | Texto | variável da ação 2 |
| `category` | Texto | variável `Categoria` |

Trate o atalho como uma senha: ele contém o token. Não compartilhe.

## Campos aceitos

| Campo | Obrigatório | Descrição |
|---|---|---|
| `amount` | Sim | `12.50`, `12,50` ou `R$ 12,50` |
| `description` | Sim | Até 160 caracteres |
| `category` | Não | Nome da categoria, sem diferença entre maiúsculas e minúsculas |
| `account` | Não | Nome da conta. Com uma só conta ativa, ela é usada automaticamente |
| `card` | Não | Nome do cartão: registra como compra no cartão |
| `installments` | Não | Parcelas, de 1 a 48, junto com `card` |
| `payment_method` | Não | `pix`, `debit`, `cash`, `boleto`, `transfer` ou `other` |
| `request_id` | Não | Identificador único do envio, para evitar duplicidade |

- Com várias contas e sem `account`, a despesa fica **pendente**, para você escolher depois.
- Sem `request_id`, dois envios com mesmo valor e descrição em cerca de 2 minutos contam como
  repetição. Quem precisar registrar dois gastos iguais em seguida deve enviar `request_id`.
- O limite é de 30 requisições por minuto, por token.

## Ver as opções disponíveis

`GET /api/integrations/options`, com o mesmo cabeçalho, devolve categorias, contas e cartões.

## Testar pelo computador

```bash
curl -X POST https://SEU-DOMINIO/api/integrations/expenses \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount":"27,90","description":"Café","category":"Lazer"}'
```
