import type { ProductAvailabilityService } from "../services/product-availability.service.ts";
import type { RequestContext } from "../http/router.ts";
import { json, type HttpResponse } from "../http/response.ts";

export class ProductsController {
  readonly #availability: ProductAvailabilityService;

  constructor(availability: ProductAvailabilityService) {
    this.#availability = availability;
  }

  /**
   * GET /api/products/:id/availability
   *
   * Errors are thrown, not returned: the server's error mapper owns the
   * translation from domain failure to status code, so this stays one line of
   * intent.
   */
  getAvailability = (ctx: RequestContext): HttpResponse => {
    return json(200, this.#availability.getAvailability(ctx.params["id"]));
  };
}
