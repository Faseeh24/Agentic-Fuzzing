
from hypothesis import strategies as st

@st.composite
def xml_strategy(draw):
    choice = draw(st.integers(min_value=0, max_value=5))
    if choice == 0:
        return "<root/>"
    elif choice == 1:
        return "<root>hello</root>"
    elif choice == 2:
        return "<root><a></b></root>"  # mismatched tags
    elif choice == 3:
        return "not xml at all"
    elif choice == 4:
        return "<root>bad < char</root>"  # bare <
    else:
        return ""  # empty
