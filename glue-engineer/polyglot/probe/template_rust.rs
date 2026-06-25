// Dynamic probe for Rust crate — compile-time check
fn main() {
    println!("{{\"probed_symbols\": []}}");
    // Cargo will resolve the crate at compile time
    // Add `use {package}::*;` to detect symbols
}
