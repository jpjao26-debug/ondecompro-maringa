# OndeCompro em Maringá?

App pessoal (sem fins comerciais) que compara os preços dos mercados de Maringá.
Roda no mesmo PC do OndeCompro de Ubatuba, logo depois da coleta de Ubatuba.

## Mercados

| Mercado | De onde vem o preço |
|---|---|
| Muffato | Loja online **João Paulino** (o Muffato do Catuaí não vende online) |
| Atacadão | Loja **Fernão Dias**, pelo site |
| Amigão | Loja online de Maringá |
| Condor | Loja **Av. Paraná**, pelo site (abre o navegador minimizado, igual ao Semar) |
| Assaí | **Só encarte** (Jornal de Ofertas das lojas de Maringá) |
| Lejon | **Só encarte** (site lejonautoservico.com.br) |
| Max Atacadista | **Só encarte** (loja Av. Colombo, 2720) |

Os encartes são lidos pelo Gemini (plano grátis), com a mesma chave do OndeCompro de Ubatuba
(o robô procura o `chaves.env` na pasta `ondecompro` da Área de Trabalho; não precisa copiar).

## Instalar

1. Crie no GitHub um repositório **público** chamado `ondecompro-maringa` (sem README).
2. Dê dois cliques em `instalar.bat` e cole o endereço do repositório quando pedir.
3. No GitHub: Settings → Pages → Branch **gh-pages** → Save.
4. No celular, abra `https://SEU-USUARIO.github.io/ondecompro-maringa/` no Chrome e toque em **Instalar app**.

## Arquivos úteis

- `rodar_agora.bat` — roda a coleta agora.
- `publicar_agora.bat` — publica o que já foi coletado, sem ler encartes.
- `logs/` — o resumo de cada coleta.
