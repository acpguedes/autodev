// Hand-written Swagger UI bootstrap (E18-S2). Kept in a separate same-origin
// file because the strict Content-Security-Policy (default-src 'self') blocks
// inline <script> bodies, which is exactly what FastAPI's built-in
// get_swagger_ui_html() emits.
window.addEventListener("load", function () {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
  });
});
