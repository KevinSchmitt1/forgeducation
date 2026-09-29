"""The local, single-tenant, bring-your-own-key web front door (doc 25, Lane 8).

`forged ui` (or `python -m forged.ui`) serves a Gradio app that authors the run inputs,
plans, lets the user edit the plan at the cost gate, and launches the build. The UI
logic lives in the gradio-free `front_door` module; `app` only wires widgets to it.
Requires the optional extra: `pip install 'forged[ui]'`.
"""
