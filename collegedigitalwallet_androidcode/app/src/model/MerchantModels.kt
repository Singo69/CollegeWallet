package com.example.collegedigitalwallet.model



data class MerchantListResponse(
    val status: String,
    val networkId: String? = null,
    val ttlSeconds: Int? = null,
    val merchants: List<String> = emptyList(),
    val message: String? = null
)