// Local development entry point only; Vercel uses the default export of app.ts.
import app from "./app.js";

const port = Number(process.env.PORT ?? 4000);
app.listen(port, () => {
  console.log(`moviespk-api listening on http://localhost:${port}`);
});
