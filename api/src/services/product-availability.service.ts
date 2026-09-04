import { NotFoundError } from "../domain/errors.ts";
import type { ProductAvailability } from "../domain/product.ts";
import type { ProductRepository } from "../repositories/product.repository.ts";
import { parseProductId } from "../validation/product-id.ts";

export class ProductAvailabilityService {
  readonly #products: ProductRepository;

  constructor(products: ProductRepository) {
    this.#products = products;
  }

  /**
   * @param rawProductId The ID exactly as it came off the URL.
   * @throws ValidationError if the ID is not a positive integer.
   * @throws NotFoundError if no such product exists.
   */
  getAvailability(rawProductId: string | undefined): ProductAvailability {
    const productId = parseProductId(rawProductId);

    const inventory = this.#products.findInventoryByProductId(productId);
    if (inventory === null) {
      throw new NotFoundError("Product", String(productId));
    }

    return {
      productId: String(inventory.productId),
      // "In stock" is the only useful reading of availability here; a
      // reservations or backorder concept would change this, and would belong
      // in the repository query rather than in this comparison.
      available: inventory.quantity > 0,
      quantity: inventory.quantity,
    };
  }
}
