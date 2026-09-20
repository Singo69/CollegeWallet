package com.example.collegedigitalwallet.model

data class TransactionItem(
    val id: Int,
    val amount: Double,
    val method: String,
    val status: String,
    val note: String?,
    val created_at: String,
    val sender_username: String,
    val receiver_username: String
)

data class TransactionListResponse(
    val status: String,
    val username: String,
    val transactions: List<TransactionItem>
)
