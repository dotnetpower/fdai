# Emit one object per managed resource instance in a raw `terraform state pull` document: its
# Terraform address, resource type, and recorded attributes. Unlike `terraform show -json`, this
# never decodes state through the provider schema, so state written by an older provider version
# stays readable before the next apply rewrites it.
.resources[]? |
select(.mode == "managed") |
. as $resource |
.instances[]? |
{
  address: (
    (if ($resource.module // "") == "" then "" else $resource.module + "." end) +
    $resource.type + "." + $resource.name +
    (if .index_key == null then ""
     elif (.index_key | type) == "number" then "[\(.index_key)]"
     else "[\(.index_key | tojson)]" end)
  ),
  type: $resource.type,
  attributes: (.attributes // {})
}
