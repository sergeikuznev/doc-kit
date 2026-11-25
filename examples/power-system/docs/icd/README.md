# Interfaces (ICD)

An interface control document is the contract between two parts that must
agree: a packet format, a pinout, a list of ROS2 topics, a UART protocol.
Write one file per interface. Change the ICD first, then the code on both sides.

Suggested structure:

```markdown
# ICD: <name>
- Version: 1
- Between: <part A> and <part B>
- Rate: <how often>

| Byte / pin / topic | Field | Type | Meaning |
|---|---|---|---|

## Change log
| Version | Date | Change |
|---|---|---|
```

If an interface is shared with another repository, keep the master copy there
and link to it from here, so there is only one version.
