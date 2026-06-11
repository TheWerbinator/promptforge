import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/** MSW server for the Next.js node runtime — started from instrumentation.ts. */
export const server = setupServer(...handlers);
