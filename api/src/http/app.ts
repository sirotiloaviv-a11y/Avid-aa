import type { DatabaseSync } from "node:sqlite";
import { ProductsController } from "../controllers/products.controller.ts";
import { SqliteProductRepository } from "../repositories/product.repository.ts";
import { ProductAvailabilityService } from "../services/product-availability.service.ts";
import { mapErrorToResponse } from "./error-mapper.ts";
import { errorResponse, type HttpResponse } from "./response.ts";
import { Router } from "./router.ts";

/**
 * Wires the object graph and returns a `handle` function: method and path in,
 * status and body out.
 *
 * Keeping the application this side of `node:http` is what lets the route
 * tests exercise real routing, real validation and a real database without
 * binding a port.
 */
export function createApp(db: DatabaseSync): (method: string, path: string) => HttpResponse {
  const products = new SqliteProductRepository(db);
  const availability = new ProductAvailabilityService(products);
  const controller = new ProductsController(availability);

  const router = new Router().add(
    "GET",
    "/api/products/:id/availability",
    controller.getAvailability,
  );

  return (method, path) => {
    const matched = router.match(method, path);
    if (matched === null) {
      return errorResponse(404, "NOT_FOUND", `No route for ${method} ${path}`);
    }

    try {
      return matched.handler(matched.ctx);
    } catch (error) {
      return mapErrorToResponse(error);
    }
  };
}
