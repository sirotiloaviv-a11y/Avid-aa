/**
 * A product's stock position as the API reports it.
 *
 * `productId` is a string rather than a number: IDs are opaque identifiers to
 * every consumer of this API, and serialising them as strings keeps the
 * contract stable if the underlying key type ever widens.
 */
export interface ProductAvailability {
  readonly productId: string;
  readonly available: boolean;
  readonly quantity: number;
}

/** What the inventory read returns for a product that exists. */
export interface ProductInventory {
  readonly productId: number;
  readonly quantity: number;
}
