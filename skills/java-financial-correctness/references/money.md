# Money

What scale each kind of value takes, where rounding happens, and how an amount is stored
and sent. The facts were checked on 2026-10-23 on JDK 25.0.5, PostgreSQL 18.6 with
pgjdbc 42.7.14, Jackson 3.2.4 and 2.22.4, ICU4J 79.1, and ISO 4217's list of 2026-09-17.

## Contents

- Kinds of value
- The rounding policy
- Minor units come from the currency
- A cash step is not a scale
- Intermediate values
- Allocation
- BigDecimal traps
- Storage in Postgres
- On the wire
- Two rounding modes are an audit signal

## Kinds of value

| Kind | Precision | Rounded |
|---|---|---|
| Posted amount: a posting, a payment, a fee charged | The currency's minor units | Once, by the policy, where it is posted |
| Intermediate value: interest before posting, a converted amount before posting | Exact, or the policy's one `MathContext` | Never to the currency's scale |
| Unit price | The instrument's own precision, which may be 8 decimals | Never to the currency's scale |
| Quantity | The instrument's own: whole shares, or fractional fund units | Only by the instrument's own rule |
| FX rate | The precision of its source | Never to either currency's scale |
| Cash amount | The cash step that the policy names | By the step function |

A type per kind keeps them apart. `Money` holds a posted amount, and its constructor
refuses any scale but `MinorUnits.of(currency)`. A price, a rate or a quantity has a type
of its own, or at least a name that says what it is, and is never a `Money`.

## The rounding policy

One table in code gives each business operation its rounding mode. The operation names
the boundary where it rounds, and the method names the unit: the currency's minor units,
or a cash step. Every rounding call goes through it. A `setScale` with a mode anywhere
else is a finding. The modes are decisions of the business, a counterparty or a
regulator, and each one records its source. The modes here are examples.

```java
public enum Rounding {
    // The accounting policy's rounding section: postings, fees and conversions round half to even.
    POSTING(RoundingMode.HALF_EVEN),
    FEE(RoundingMode.HALF_EVEN),
    FX_CONVERSION(RoundingMode.HALF_EVEN),
    // The card scheme's fee schedule: each scheme fee rounds half up.
    CARD_SCHEME_FEE(RoundingMode.HALF_UP);

    public static final MathContext INTERMEDIATE = MathContext.DECIMAL128;

    private final RoundingMode mode;

    Rounding(RoundingMode mode) {
        this.mode = mode;
    }

    public Money toMinorUnits(BigDecimal value, Currency currency) {
        return new Money(value.setScale(MinorUnits.of(currency), mode), currency);
    }

    public BigDecimal toCashStep(BigDecimal value, BigDecimal step) {
        return value.divide(step, 0, mode).multiply(step);
    }
}
```

The boundary is the point where a value becomes a posted amount: the posting itself, the
fee charged, the converted amount booked. Display rounds a copy for the screen, and that
copy never flows back into a computation. `POSTING` turns 2.345 CHF into 2.34, and
`CARD_SCHEME_FEE` turns it into 2.35.

## Minor units come from the currency

- `Currency.getDefaultFractionDigits()` is ISO 4217's minor unit: JPY 0, CHF 2, BHD 3,
  CLF 4. Never assume 2.
- It returns -1 for a pseudo-currency such as XAU or XDR. `MinorUnits.of` refuses those,
  unless the policy gives such a currency a scale because the business books it.

  ```java
  public static int of(Currency currency) {
      int digits = currency.getDefaultFractionDigits();
      if (digits < 0) {
          throw new IllegalArgumentException(currency + " has no minor unit");
      }
      return digits;
  }
  ```

- The JDK's currency table can lag ISO's. On JDK 25.0.5, `Currency.getInstance("UYW")`
  threw `IllegalArgumentException`, although ISO 4217 lists UYW with 4 minor units. A
  currency the JDK does not know fails closed. The system property
  `java.util.currency.data` names a file whose entries are keyed by country, so an entry
  can replace a country's currency: `UY=UYW,927,4` made UYW known and
  `Currency.getInstance("UYU")` throw. The same entry under the unused code `ZZ` added UYW
  beside UYU.
- CLDR's digits are display data, and some differ from ISO 4217's: HUF has 0 against 2,
  and IQD 0 against 3, in CLDR's supplemental data and in ICU4J 79.1. The ledger posts
  ISO 4217's minor units. A screen may show CLDR's.

## A cash step is not a scale

CLDR gives CHF and CAD a cash rounding of 0.05, DKK 0.50 and HUF 5. ICU4J returns these
from `getRoundingIncrement(CurrencyUsage.CASH)` as a `double`, and the JDK has no such
data. `setScale` cannot express a step: `setScale(2, HALF_UP)` leaves 12.33 as it is. A
cash amount takes its own function, `toCashStep` in the policy, with the step and the mode
from the policy.
With a 0.05 step, 12.33 becomes 12.35, and 12.325 becomes 12.35 under `HALF_UP` or 12.30
under `HALF_EVEN`. The result keeps the step's scale. The step applies where cash changes
hands. An account balance stays at the minor unit.

## Intermediate values

- `add`, `subtract` and `multiply` without a `MathContext` are exact, and the scale grows:
  1.10 × 2.005 is 2.20550, and 1.0001 to the power 365, computed exactly, has 1,461 digits.
- `divide` without a scale or a `MathContext` throws `ArithmeticException` on a quotient
  that does not terminate, such as 1/3.
- So the policy states one `MathContext` for intermediate values. `DECIMAL128` holds 34
  digits and rounds `HALF_EVEN`. Every division, every `pow` and every long chain of
  multiplications passes it.
- A division never takes a currency's scale, and neither does a rate. A GBP to EUR rate of
  1.1538, stored at EUR's 2 decimals as 1.15, converts 250,000.00 GBP to 287,500.00 EUR
  instead of 288,450.00.
- Round once, at the boundary, after the multiplication. A price of 3.456789 rounded to
  3.46 before it is multiplied by 50,000 values the position at 173,000.00 instead of
  172,839.45.

## Allocation

Splitting an amount, such as a fee across accounts or a payment across invoices, uses the
largest remainder. Each share gets the whole minor units of its exact portion. The units
left over go one each to the largest remainders, and a tie goes to the earliest share.
The shares always sum to the total. The arithmetic is in integers, so it needs no
`MathContext`.

```java
public static List<Money> byLargestRemainder(Money total, List<BigDecimal> weights) {
    int scale = weights.stream().mapToInt(BigDecimal::scale).max().orElseThrow();
    List<BigInteger> parts = weights.stream().map(w -> w.setScale(scale).unscaledValue()).toList();
    BigInteger sum = parts.stream().reduce(BigInteger.ZERO, BigInteger::add);
    if (parts.stream().anyMatch(p -> p.signum() < 0) || sum.signum() == 0) {
        throw new IllegalArgumentException("weights must be non-negative and not all zero: " + weights);
    }
    BigInteger units = total.amount().unscaledValue().abs();
    List<BigInteger> shares = new ArrayList<>();
    List<BigInteger> remainders = new ArrayList<>();
    for (BigInteger part : parts) {
        BigInteger[] quotientAndRemainder = units.multiply(part).divideAndRemainder(sum);
        shares.add(quotientAndRemainder[0]);
        remainders.add(quotientAndRemainder[1]);
    }
    BigInteger left = units.subtract(shares.stream().reduce(BigInteger.ZERO, BigInteger::add));
    IntStream.range(0, parts.size()).boxed()
            .sorted(Comparator.comparing(remainders::get).reversed())
            .limit(left.longValueExact())
            .forEach(i -> shares.set(i, shares.get(i).add(BigInteger.ONE)));
    int sign = total.amount().signum();
    return shares.stream()
            .map(s -> new Money(new BigDecimal(sign < 0 ? s.negate() : s, total.amount().scale()), total.currency()))
            .toList();
}
```

100.00 CHF in three equal shares gives 33.34, 33.33 and 33.33. 100 JPY gives 34, 33 and
33. -100.00 CHF gives -33.34, -33.33 and -33.33. 10.01 CHF by 50:30:20 gives 5.01, 3.00
and 2.00. `total` is a `Money`, so its unscaled value counts minor units.

## BigDecimal traps

- `equals` compares the scale: 2.0 and 2.00 are not equal, and a `HashSet` keeps both.
  Compare amounts with `compareTo` or `signum()`. A record that holds a `BigDecimal`
  inherits this `equals`, which is one more reason `Money` fixes its scale.
- `new BigDecimal(0.1)` is 0.1000000000000000055511151231257827021181583404541015625.
  Build an amount from a `String` or from a `long` and a scale. `BigDecimal.valueOf(0.1)`
  goes through `Double.toString` and gives 0.1, but `BigDecimal.valueOf(0.1f)` gives
  0.10000000149011612. Money never passes through a `float` or a `double`.
- A `MathContext` sets significant digits, not decimals: `1234.56` rounded with
  `new MathContext(2)` is `1.2E+3`. Decimals are `setScale`.
- `setScale(n)` without a mode throws `ArithmeticException: Rounding necessary` when it
  would have to round. It asserts that an amount already has the expected scale.
- `stripTrailingZeros()` turns 100.00 into `1E+2`, and `toString()` prints it that way.
  `toPlainString()` prints 100.
- `unscaledValue()` depends on the scale: 12.34 gives 1234, and 12.340 gives 12340. Integer
  minor units come from `amount.movePointRight(MinorUnits.of(currency)).longValueExact()`,
  which throws on a leftover fraction. The way back is `BigDecimal.valueOf(units, digits)`.

## Storage in Postgres

- A declared scale rounds silently, ties away from zero, which is Java's `HALF_UP`:
  `numeric(10,2)` stores 2.345 as 2.35 and -2.345 as -2.35. A `HALF_EVEN` policy would
  lose at the column. Each column's scale is at least the scale the policy writes, so the
  database never rounds.
- A declared scale also pads: 12.3 in a `numeric(19,4)` column reads back as 12.3000, which
  is not `equals` to 12.3. The repository normalises on read with `setScale` and no mode,
  which throws rather than rounds.
- Too many digits before the point fail: 1234.5 into `numeric(5,2)` raises
  `numeric field overflow`.
- An unconstrained `numeric` keeps the scale it was given, so 12.30 stays 12.30. On such a
  column, a check rejects a value off its currency's minor units instead of rounding it.
  With the minor units in a column of the same row,
  `CHECK (amount = round(amount, minor_units))` rejected CHF 12.345 and JPY 12.5, and
  accepted CHF 12.300 and BHD 1.234. A constant 2 rejected BHD 1.234.
- Each kind of value gets its own column type. A posted amount takes the minor units the
  ledger books. A price keeps the instrument's precision, and 8 decimals is a correct
  price. A rate keeps its source's precision.

## On the wire

- An amount crosses JSON as a decimal string with its currency beside it:
  `{"amount": "12.30", "currency": "CHF"}`.
- Jackson reads a JSON number into a `BigDecimal` field exactly, trailing zeros included,
  in 3.2.4 and in 2.22.4. The string protects everything around that field:
  - An untyped `Map` or a `JsonNode` reads the number as a `Double` (0.12345678901234568),
    unless `DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS` is on. With it on, a
    2.22.4 `JsonNode` still dropped trailing zeros, 1234.50 to 1234.5 and 100.00 to
    1E+2, where 3.2.4 kept them.
  - JavaScript's `JSON.parse` reads every number as a double: 1234.50 became 1234.5, and
    0.123456789012345678901 became 0.12345678901234568.
  - Jackson writes a `BigDecimal` such as `1E+3` in scientific notation unless
    `StreamWriteFeature.WRITE_BIGDECIMAL_AS_PLAIN` is on, and `JsonFormat.Shape.STRING`
    alone writes `"1E+3"`.
- One mapper setting covers every `BigDecimal`. It wrote `"12.30"` and `"1000"`, and read
  `"12.30"` back with its scale, in both Jackson versions:

  ```java
  JsonMapper mapper = JsonMapper.builder()
          .withConfigOverride(BigDecimal.class, o -> o.setFormat(JsonFormat.Value.forShape(JsonFormat.Shape.STRING)))
          .enable(StreamWriteFeature.WRITE_BIGDECIMAL_AS_PLAIN)
          .build();
  ```

- Integer minor units go on the wire only where the counterparty's API defines them, and
  they convert with the currency's minor units, never with a factor of 100.

## Two rounding modes are an audit signal

Two modes in one codebase are not a defect in themselves. They prompt a check of every
call site against the policy. A site the policy does not cover, or one that contradicts
it, is a finding. A site that matches a documented counterparty or regulatory rule is
not. A mode with no recorded source is a question for the business, not a choice for the
reviewer.
