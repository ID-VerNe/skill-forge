// Dynamic probe for npm package
const pkg = "{package}";

try {
  const mod = require(pkg);
  const results: any[] = [];
  for (const key of Object.keys(mod)) {
    if (key.startsWith("_")) continue;
    const val = mod[key];
    results.push({
      symbol: key,
      resolved: true,
      return_type: typeof val,
      error: "",
      signature: typeof val === "function" ? val.toString().split("\n")[0] : ""
    });
  }
  console.log(JSON.stringify({ probed_symbols: results }, null, 2));
} catch (e: any) {
  console.error("Probe failed:", e.message);
}
