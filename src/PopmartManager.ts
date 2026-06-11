export interface PopItem {
  id: string;
  name: string;
  series: string;
  ip: string;
  price: number;
  is_chaser: boolean;
  image?: string;
  stock_count: number;
  updated_at?: string;
}

type SoldCompsRow = {
  price?: number | string;
  computedPrice?: number | string;
  priceWithShipping?: number | string;
  soldPrice?: number | string;
};

export class PopmartManager {
  private items: PopItem[] = [];
  private apiKey = "";
  private storage: Storage;

  constructor(initialData: PopItem[], apiKey?: string, storage: Storage = window.localStorage) {
    this.storage = storage;
    this.items = initialData;
    this.apiKey = apiKey || this.storage.getItem("SOLD_COMPS_API_KEY") || "";
  }

  public updateApiKey(newKey: string): void {
    this.apiKey = newKey.trim();
    this.storage.setItem("SOLD_COMPS_API_KEY", this.apiKey);
  }

  public getAllItems(): PopItem[] {
    return [...this.items];
  }

  public loadPersistedItems(): PopItem[] {
    const primary = this.storage.getItem("poptracker_user_products");
    const legacy = this.storage.getItem("poptracker_h5_products");
    const raw = primary || legacy;
    if (!raw) return this.getAllItems();
    try {
      const parsed = JSON.parse(raw);
      this.items = Array.isArray(parsed) ? parsed : Object.values(parsed);
      return this.getAllItems();
    } catch {
      return this.getAllItems();
    }
  }

  public saveItem(item: PopItem): void {
    const index = this.items.findIndex((candidate) => candidate.id === item.id);
    if (index >= 0) {
      this.items[index] = { ...this.items[index], ...item };
    } else {
      this.items.unshift(item);
    }
    this.persistData();
  }

  public deleteItem(id: string): void {
    this.items = this.items.filter((item) => item.id !== id);
    this.persistData();
  }

  public changeStock(id: string, delta: number): PopItem | null {
    const item = this.items.find((candidate) => candidate.id === id);
    if (!item) return null;
    item.stock_count = Math.max(0, item.stock_count + delta);
    this.persistData();
    return item;
  }

  public totalAssetValue(): number {
    return this.items.reduce((sum, item) => sum + item.price * item.stock_count, 0);
  }

  public totalStockCount(): number {
    return this.items.reduce((sum, item) => sum + item.stock_count, 0);
  }

  public async refreshMarketPrice(id: string): Promise<number | null> {
    const item = this.items.find((candidate) => candidate.id === id);
    if (!item || !this.apiKey) return null;

    const endpoint = `https://api.apify.com/v2/acts/caffein.dev~ebay-sold-listings/run-sync-get-dataset-items?token=${encodeURIComponent(this.apiKey)}`;
    const keyword = `Pop Mart ${item.ip} ${item.series} ${item.name} blind box loose`;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword, count: 10, daysToScrape: 30 }),
      });
      if (!response.ok) return null;

      const rows = (await response.json()) as SoldCompsRow[];
      const prices = rows
        .map((row) => this.toNumber(row.priceWithShipping || row.computedPrice || row.price || row.soldPrice))
        .filter((price) => price > 1)
        .sort((a, b) => a - b);
      if (!prices.length) return null;

      const freshPrice = Number(prices[Math.floor(prices.length / 2)].toFixed(2));
      item.price = freshPrice;
      item.updated_at = new Date().toISOString().slice(0, 10);
      this.persistData();
      return freshPrice;
    } catch {
      return null;
    }
  }

  private persistData(): void {
    this.storage.setItem("poptracker_user_products", JSON.stringify(this.items));
  }

  private toNumber(value: number | string | undefined): number {
    if (typeof value === "number") return value;
    return Number(String(value || "0").replace(/[^0-9.-]/g, "")) || 0;
  }
}
