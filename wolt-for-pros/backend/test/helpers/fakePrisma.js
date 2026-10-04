// In-memory stand-in for the subset of the Prisma client the services use:
// findUnique/findFirst/findMany/count/create/update/updateMany/upsert with
// equality, in, gt/gte/lt/lte, not, OR/AND filters, increment/decrement,
// nested create and include. Decimal columns are kept as strings like Prisma
// returns them. $transaction rolls back on throw (sequential use only).
const DECIMAL_FIELDS = new Set(['balance', 'lockedBalance', 'amount', 'estimatedPrice', 'finalPrice', 'platformFee']);
const KEYS = { user: 'id', tradespersonProfile: 'userId', wallet: 'id', job: 'id', walletTransaction: 'id' };
const UNIQUES = { user: ['phone'], tradespersonProfile: ['licenseNumber'], wallet: ['tradespersonId'], walletTransaction: ['externalRef'] };
const DEFAULTS = {
  wallet: { balance: '0.00', lockedBalance: '0.00' },
  job: { codeAttempts: 0, status: 'requested', tradespersonId: null, platformFee: null, finalPrice: null, flaggedAt: null, resolution: null },
  tradespersonProfile: { fraudScore: 0, status: 'inactive' },
  user: { latitude: null, longitude: null },
};

const isPlainObject = (v) => v !== null && typeof v === 'object' && !(v instanceof Date);
const comparable = (v) => (v instanceof Date ? v.getTime() : typeof v === 'string' && v !== '' && !Number.isNaN(Number(v)) ? Number(v) : v);

function matchValue(value, cond) {
  if (cond === null) return value === null || value === undefined;
  if (!isPlainObject(cond)) return comparable(value) === comparable(cond);
  return Object.entries(cond).every(([op, x]) => {
    const a = comparable(value);
    const b = comparable(x);
    switch (op) {
      case 'in': return x.includes(value);
      case 'not': return !matchValue(value, x);
      case 'gt': return a != null && a > b;
      case 'gte': return a != null && a >= b;
      case 'lt': return a != null && a < b;
      case 'lte': return a != null && a <= b;
      default: throw new Error(`fakePrisma: unsupported filter ${op}`);
    }
  });
}

function matchWhere(row, where = {}) {
  return Object.entries(where).every(([k, c]) => {
    if (k === 'OR') return c.some((w) => matchWhere(row, w));
    if (k === 'AND') return c.every((w) => matchWhere(row, w));
    return matchValue(row[k], c);
  });
}

function createFakePrisma() {
  let db = { user: [], tradespersonProfile: [], wallet: [], job: [], walletTransaction: [] };
  let seq = 0;

  const withRelations = (model, row, include) => {
    if (!include || !row) return row;
    const out = { ...row };
    for (const [rel, spec] of Object.entries(include)) {
      if (!spec) continue;
      let related = null;
      if (model === 'job' && rel === 'client') related = db.user.find((u) => u.id === row.clientId);
      else if (model === 'job' && rel === 'tradesperson') related = db.user.find((u) => u.id === row.tradespersonId);
      else if (model === 'user' && rel === 'profile') related = db.tradespersonProfile.find((p) => p.userId === row.id);
      else if (model === 'user' && rel === 'wallet') related = db.wallet.find((w) => w.tradespersonId === row.id);
      else throw new Error(`fakePrisma: unsupported include ${model}.${rel}`);
      out[rel] = related ? withRelations('user', { ...related }, isPlainObject(spec) ? spec.include : null) : null;
    }
    return out;
  };

  const apply = (row, data) => {
    for (const [k, v] of Object.entries(data)) {
      if (isPlainObject(v) && ('increment' in v || 'decrement' in v)) {
        const delta = 'increment' in v ? Number(v.increment) : -Number(v.decrement);
        const next = Math.round((Number(row[k] || 0) + delta) * 100) / 100;
        row[k] = DECIMAL_FIELDS.has(k) ? next.toFixed(2) : next;
      } else if (isPlainObject(v) && 'create' in v) {
        // nested create: handled by create()
      } else {
        row[k] = DECIMAL_FIELDS.has(k) && v != null ? Number(v).toFixed(2) : v;
      }
    }
  };

  const assertUnique = (model, row) => {
    for (const field of UNIQUES[model] || []) {
      if (row[field] != null && db[model].some((r) => r !== row && r[field] === row[field])) {
        throw Object.assign(new Error(`Unique constraint failed on ${model}.${field}`), { code: 'P2002' });
      }
    }
  };

  const model = (name) => ({
    /** @param {any} [args] */
    async findUnique({ where, include } = {}) {
      const row = db[name].find((r) => matchWhere(r, where));
      return row ? withRelations(name, { ...row }, include) : null;
    },
    /** @param {any} [args] */
    async findFirst({ where, include } = {}) {
      const row = db[name].find((r) => matchWhere(r, where));
      return row ? withRelations(name, { ...row }, include) : null;
    },
    /** @param {any} [args] */
    async findMany({ where, include, take } = {}) {
      return db[name].filter((r) => matchWhere(r, where)).slice(0, take || Infinity).map((r) => withRelations(name, { ...r }, include));
    },
    /** @param {any} [args] */
    async count({ where } = {}) {
      return db[name].filter((r) => matchWhere(r, where)).length;
    },
    /** @param {any} args */
    async create({ data, include }) {
      seq += 1;
      const row = { createdAt: new Date(), ...DEFAULTS[name], [KEYS[name]]: data[KEYS[name]] || `${name}_${seq}` };
      apply(row, data);
      assertUnique(name, row);
      db[name].push(row);
      if (data.profile) await model('tradespersonProfile').create({ data: { ...data.profile.create, userId: row.id } });
      if (data.wallet) await model('wallet').create({ data: { ...data.wallet.create, tradespersonId: row.id } });
      return withRelations(name, { ...row }, include);
    },
    /** @param {any} args */
    async update({ where, data, include }) {
      const row = db[name].find((r) => matchWhere(r, where));
      if (!row) {
        throw Object.assign(new Error(`${name} not found`), { code: 'P2025' });
      }
      apply(row, data);
      assertUnique(name, row);
      return withRelations(name, { ...row }, include);
    },
    /** @param {any} args */
    async updateMany({ where, data }) {
      const rows = db[name].filter((r) => matchWhere(r, where));
      rows.forEach((r) => apply(r, data));
      return { count: rows.length };
    },
    /** @param {any} args */
    async upsert({ where, create, update }) {
      const row = db[name].find((r) => matchWhere(r, where));
      if (row) {
        apply(row, update);
        return { ...row };
      }
      return this.create({ data: { ...where, ...create } });
    },
  });

  const client = {
    async $transaction(fn) {
      const snapshot = structuredClone(db);
      try {
        return await fn(client);
      } catch (err) {
        db = snapshot;
        throw err;
      }
    },
    async $disconnect() {},
    _reset() {
      db = { user: [], tradespersonProfile: [], wallet: [], job: [], walletTransaction: [] };
    },
  };
  for (const name of Object.keys(KEYS)) Object.defineProperty(client, name, { get: () => model(name) });
  return client;
}

module.exports = { createFakePrisma };
