# Business Rules


1. **Valid Sales & Revenue:**
   - Revenue calculation should only include completed orders (`status = 'COMPLETED'`).
   - REFUNDED and RETURNED are same.

2. **High Value Products:**
   - A product is considered "Expensive" or "High Value" if its `price > 1000`.

