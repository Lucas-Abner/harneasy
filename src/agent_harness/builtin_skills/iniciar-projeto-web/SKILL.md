---
name: "iniciar-projeto-web"
description: "Criar site ou app web simples (HTML, CSS e JS sem build)"
triggers:
  - "site"
  - "pagina web"
  - "html"
  - "css"
  - "frontend"
  - "landing page"
---
# Iniciar um projeto web simples

Sem rede: não use npm install nem CDNs. Escreva HTML, CSS e JavaScript puros.

## Estrutura
```
index.html
css/estilo.css
js/app.js
README.md
```

## Passos
1. `index.html` com a estrutura básica, ligando o CSS e o JS:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nome</title>
  <link rel="stylesheet" href="css/estilo.css">
</head>
<body>
  <main id="app"></main>
  <script src="js/app.js"></script>
</body>
</html>
```

2. CSS: variáveis em `:root` para cores e espaçamentos; layout com flexbox ou grid.
3. JS: funções pequenas; o estado em um objeto; uma função `render()` que
   redesenha a tela a partir do estado; `localStorage` para salvar dados.
4. Verifique a sintaxe do JS com `node --check js/app.js` (se o node existir).
5. Para lógica complexa, separe funções puras num arquivo e teste-as com
   `node` e `console.assert`.
6. No README, diga para abrir `index.html` no navegador.
