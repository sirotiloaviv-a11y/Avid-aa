// Switches the Prisma datasource provider between sqlite and postgresql.
// Prisma does not read the provider from an environment variable.
const fs = require('fs');
const path = require('path');

const provider = process.argv[2];
if (!['sqlite', 'postgresql'].includes(provider)) {
  console.error('Usage: node scripts/set-db-provider.js <sqlite|postgresql>');
  process.exit(1);
}

const schemaPath = path.join(__dirname, '..', 'prisma', 'schema.prisma');
const schema = fs.readFileSync(schemaPath, 'utf8');
const updated = schema.replace(
  /(datasource db \{\s*provider\s*=\s*)"[^"]+"/,
  `$1"${provider}"`,
);
fs.writeFileSync(schemaPath, updated);
console.log(`Prisma provider set to ${provider}. Update DATABASE_URL, then run npm run db:push.`);
