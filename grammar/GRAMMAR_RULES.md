# mxml Grammar Rules

This document contains the complete grammar rules for mxml's XML parser,
derived from the ANTLR reference grammar and verified against mxml source.

## Token Rules (Lexer)

### TEXT
- Pattern: `~[<&]+` (any char except `<` and `&`)
- mxml constraint: No control chars < 0x20 except `\t`, `\n`, `\r`

### COMMENT
- Pattern: `<!-- ... -->`
- Must have well-formed `--\>` terminator

### CDATA
- Pattern: `<![CDATA[ ... ]]>`
- Must have proper `]]>` terminator

### DTD
- Pattern: `<! ... >`
- mxml stores opaquely as DECLARATION node

### EntityRef
- Pattern: `&Name;`
- mxml constraint: ONLY `&amp;`, `&lt;`, `&gt;`, `&quot;`, `&apos;`

### CharRef
- Decimal: `&#DIGIT+;`
- Hex: `&#xHEXDIGIT+;`

### OPEN
- Pattern: `<` — pushes INSIDE mode

### Name
- mxml is permissive: accepts names starting with digits/punctuation
- ANTLR strict: `NameStartChar NameChar*`

## Parser Rules

```
document  : prolog? misc* element misc* EOF
prolog    : XMLDeclOpen attribute* SPECIAL_CLOSE
content   : chardata? ((element | reference | CDATA | PI | COMMENT) chardata?)*
element   : < Name attribute* > content < / Name > | < Name attribute* />
reference : EntityRef | CharRef
attribute : Name = STRING
chardata  : TEXT | SEA_WS
misc      : COMMENT | PI | SEA_WS
```

## mxml-Specific Behaviors

| Feature | mxml Behavior |
|---------|--------------|
| DTD blocks | Stored as opaque DECLARATION nodes |
| Entity refs | Only 5 built-in names accepted |
| Control chars | Rejected (< 0x20, except \t\n\r) |
| Encodings | UTF-8, UTF-16-BE, UTF-16-LE (BOM) |
| Element names | More permissive than ANTLR |
| Attribute values | Supports unquoted values |
| Duplicate attrs | Error: "Duplicate attribute" |
| Mismatched tags | Error: "Mismatched close tag" |
| Second root | Error: "cannot be a second root node" |
| Unterminated comment | Error: "XML declaration is not well formed" or parse error |
| Unterminated CDATA | Error: "Unexpected end of file" or parse error |
| Bad entity | Error: "Undefined entity" |

## Deliberate Break Patterns

These patterns hit named error-handling code paths in mxml and are the
highest-value fuzzing targets:

1. **Mismatched tags**: `<a><b></a></b>` → "Mismatched close tag"
2. **Duplicate attributes**: `<a x="1" x="2"/>` → "Duplicate attribute"
3. **Second root**: `<a/><b/>` → "cannot be a second root node"
4. **Bad entity**: `<root>&foo;</root>` → "Undefined entity"
5. **Unterminated comment**: `<!-- unclosed comment` → parse error
6. **Unterminated CDATA**: `<![CDATA[unclosed cdata` → parse error
