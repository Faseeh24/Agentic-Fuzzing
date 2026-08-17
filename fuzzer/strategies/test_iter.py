
from hypothesis import strategies as st

@st.composite
def xml_strategy(draw):
    name = draw(st.sampled_from(["a", "b", "root", "tag"]))
    depth = draw(st.integers(min_value=0, max_value=2))
    content = draw(st.sampled_from(["hello", "", "data"]))
    if depth == 0:
        return f"<{name}/>"
    inner = f"<{name}>{content}</{name}>"
    for _ in range(depth - 1):
        inner = f"<{name}>{inner}</{name}>"
    return inner
