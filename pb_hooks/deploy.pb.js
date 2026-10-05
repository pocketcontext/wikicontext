/// <reference path="../pb_data/types.d.ts" />
// Deployment behaviour: the health check and the settings taken from the environment. The logic is in deploy.js.

// Health check for the container platform. Outside /api/, so no rate limit rule matches it; successful
// checks are kept out of the request log.
routerAdd("GET", "/up", (e) => require(`${__hooks}/deploy.js`).up(e), $apis.skipSuccessActivityLog());

// Runs for every command (serve, superuser, migrate) after the database is open and the settings are loaded.
onBootstrap((e) => {
  e.next();
  // A durable server maintenance freeze keeps the stored configuration authoritative.
  // In particular, do not attempt settings or OAuth writes during a frozen restart.
  if (e.app.store().get("pocketcontextMaintenanceReadOnly") === true) return;
  require(`${__hooks}/deploy.js`).settings(e.app);
  require(`${__hooks}/deploy.js`).googleOAuth(e.app);
});
